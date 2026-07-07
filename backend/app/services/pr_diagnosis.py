"""PR 问题诊断服务 — 基于LLM分析PR状态、CI结果、Review情况，给出诊断报告"""
import asyncio
import json
import logging
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import CIResult, CIJob, PullRequest
from app.models.daily_summary import LLMProviderConfig
from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)

FALLBACK_SYSTEM_PROMPT = """你是一名资深的 vLLM Ascend 社区代码评审专家和 CI/CD 诊断工程师。
用户会提供一个 PR 的详细信息（包括标题、作者、状态、Review 情况、CI 检查结果等），
请根据这些信息生成一份 PR 诊断报告。

报告要求：
1. **PR 概况**：标题、作者、状态、分支、代码变更规模
2. **CI 诊断**：CI 是否通过、失败任务及可能原因、耗时分析
3. **Review 诊断**：Review 状态、Reviewer 情况、是否有变更请求
4. **风险点**：潜在问题（如长期未处理、CI 连续失败、代码冲突等）
5. **建议**：下一步行动建议（如修复 CI、补充 Review、处理冲突等）

报告格式：Markdown，简洁明了，每个板块先结论后数据。全文控制在 400-600 字。
如果 CI 通过且 Review 正常，报告应正面肯定 PR 的健康状态。
"""


class PRDiagnosisService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def diagnose(self, pr_number: int) -> dict:
        """诊断指定 PR，返回诊断报告"""
        # 1. Fetch PR from DB
        stmt = select(PullRequest).where(
            PullRequest.pr_number == pr_number,
            PullRequest.owner == settings.GITHUB_OWNER,
            PullRequest.repo == settings.GITHUB_REPO,
        )
        result = await self.db.execute(stmt)
        pr = result.scalar_one_or_none()
        if not pr:
            raise ValueError(f"PR #{pr_number} not found in database")

        # 2. Fetch CI results by head_sha
        ci_results = []
        ci_jobs = []
        if pr.head_sha:
            ci_stmt = select(CIResult).where(
                CIResult.head_sha == pr.head_sha,
                CIResult.status == "completed",
            )
            ci_result = await self.db.execute(ci_stmt)
            ci_results = ci_result.scalars().all()

            if ci_results:
                run_ids = [r.run_id for r in ci_results]
                job_stmt = select(CIJob).where(CIJob.run_id.in_(run_ids))
                job_result = await self.db.execute(job_stmt)
                ci_jobs = job_result.scalars().all()

        # 3. Build context
        context = self._build_context(pr, ci_results, ci_jobs)
        context += "\n\n注意：这是一次 PR 诊断请求。请基于上述 PR 信息（包括 CI 结果、Review 状态、Pipeline 阶段），运用根因分析方法论进行诊断。如果 CI 通过且 Review 正常，应正面肯定 PR 的健康状态；如果存在 CI 失败或 Review 问题，请按照根因分析方法进行深入诊断。"

        # 4. Get LLM config
        llm_config = await self._get_llm_config()

        # 5. Get system prompt (auto-bug-fixer skill)
        system_prompt = self._get_system_prompt()

        # 6. Call LLM (with 120s timeout)
        client = LLMClient()
        start_time = datetime.now()
        llm_result = await asyncio.wait_for(
            client.generate(
                provider=llm_config.provider,
                model=llm_config.default_model,
                api_key=llm_config.api_key,
                api_base=llm_config.api_base_url,
                system_prompt=system_prompt,
                user_prompt=context,
                temperature=0.3,
                max_tokens=4096,
            ),
            timeout=120,
        )
        duration = (datetime.now() - start_time).total_seconds()

        return {
            "pr_number": pr_number,
            "report": llm_result.content,
            "model": llm_config.default_model,
            "provider": llm_config.provider,
            "duration_seconds": round(duration, 1),
            "tokens": llm_result.prompt_tokens + llm_result.completion_tokens,
        }

    def _build_context(self, pr, ci_results, ci_jobs) -> str:
        """构建 LLM 上下文"""
        lines = [
            f"## PR #{pr.pr_number} 诊断请求",
            f"",
            f"### PR 基本信息",
            f"- 标题: {pr.title}",
            f"- 作者: {pr.author}",
            f"- 状态: {pr.state}" + (" (Draft)" if pr.is_draft else ""),
            f"- 分支: {pr.head_branch or 'N/A'} → {pr.base_branch or 'N/A'}",
            f"- 代码变更: +{pr.additions} -{pr.deletions} ({pr.changed_files} 文件)",
            f"- Pipeline 阶段: {pr.pipeline_stage or 'N/A'}",
            f"- Review 状态: {pr.review_status or 'N/A'}",
            f"- CI 状态: {pr.ci_status or 'N/A'}",
            f"- 创建时间: {pr.created_at}",
        ]

        if pr.merged_at:
            lines.append(f"- 合入时间: {pr.merged_at}")
        if pr.closed_at:
            lines.append(f"- 关闭时间: {pr.closed_at}")

        # Reviewers
        if pr.reviewers:
            lines.append(f"\n### Reviewers ({len(pr.reviewers)})")
            for r in pr.reviewers:
                lines.append(f"- {r.get('login', 'N/A')}: {r.get('state', 'N/A')}")

        # PR data JSON (reviews with comments)
        if pr.data:
            reviews = pr.data.get("reviews", [])
            if reviews:
                lines.append(f"\n### Review 详情 ({len(reviews)})")
                for rev in reviews[:10]:  # limit to 10 reviews
                    user = rev.get("user", {}).get("login", "N/A")
                    state = rev.get("state", "N/A")
                    body = rev.get("body", "")[:200]
                    lines.append(f"- [{state}] {user}: {body}" if body else f"- [{state}] {user}")

        # CI Results
        if ci_results:
            lines.append(f"\n### CI 检查结果 ({len(ci_results)})")
            for ci in ci_results:
                lines.append(f"- {ci.workflow_name} #{ci.run_number}: {ci.conclusion or ci.status} (耗时 {ci.duration_seconds or 0}s, 硬件: {ci.hardware or 'N/A'})")

            # CI Jobs with failed steps
            failed_jobs = [j for j in ci_jobs if j.conclusion == "failure"]
            if failed_jobs:
                lines.append(f"\n### 失败的 CI Jobs ({len(failed_jobs)})")
                for job in failed_jobs[:5]:
                    lines.append(f"- {job.job_name}: {job.conclusion}")
                    if job.steps_data:
                        try:
                            steps = json.loads(job.steps_data) if isinstance(job.steps_data, str) else job.steps_data
                            failed_steps = [s for s in steps if s.get("conclusion") == "failure"]
                            for s in failed_steps[:3]:
                                lines.append(f"  - 失败步骤: {s.get('name', 'N/A')}")
                        except (json.JSONDecodeError, TypeError):
                            pass
        else:
            lines.append(f"\n### CI 检查结果: 无关联的 CI 运行记录")

        # Computed metrics (derived from timestamps, mirroring PullRequestResponse schema)
        def _hours(end, start):
            if end and start:
                try:
                    return round((end - start).total_seconds() / 3600, 1)
                except TypeError:
                    return None
            return None

        ttr = _hours(pr.first_review_at, pr.created_at)
        ttm = _hours(pr.merged_at, pr.created_at)
        cid = _hours(pr.ci_completed_at, pr.ci_started_at)

        lines.append(f"\n### 时间指标")
        if ttr is not None:
            lines.append(f"- 首次 Review: {ttr:.1f}h")
        if ttm is not None:
            lines.append(f"- 合入耗时: {ttm:.1f}h")
        if cid is not None:
            lines.append(f"- CI 耗时: {cid:.1f}h")

        lines.append(f"\n请根据以上信息生成 PR 诊断报告。")

        return "\n".join(lines)

    def _get_system_prompt(self) -> str:
        """获取系统提示词：优先从 skill registry 加载 auto-bug-fixer 技能"""
        try:
            from app.services.skill_registry import get_skill_registry
            skill = get_skill_registry().get_skill_by_scope('ci_failure_analysis')
            if skill and skill.content:
                logger.info("Using auto-bug-fixer skill for PR diagnosis")
                return skill.content
        except Exception as e:
            logger.warning(f"Failed to load auto-bug-fixer skill, using fallback: {e}")
        return FALLBACK_SYSTEM_PROMPT

    async def _get_llm_config(self):
        """获取活跃的 LLM 配置"""
        stmt = select(LLMProviderConfig).where(LLMProviderConfig.is_active == True).limit(1)
        result = await self.db.execute(stmt)
        config = result.scalar_one_or_none()
        if not config:
            raise ValueError("No active LLM provider configured")
        if not config.api_key:
            raise ValueError(f"API Key not configured for provider: {config.provider}")
        return config
