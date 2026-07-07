"""PR 问题诊断服务 — 从 GitHub API 获取 CI 失败详情，使用 auto-bug-fixer 进行根因分析"""
import asyncio
import json
import logging
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import PullRequest
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
        self._github_client = None

    def _get_github_client(self):
        if self._github_client is None:
            from app.services.github_client import GitHubClient
            self._github_client = GitHubClient(token=settings.GITHUB_TOKEN)
        return self._github_client

    async def diagnose(self, pr_number: int) -> dict:
        """诊断指定 PR 的 CI 失败，返回诊断报告"""
        # 1. 获取 PR 信息（DB 优先，GitHub API 降级）
        pr_info = await self._get_pr_info(pr_number)
        head_sha = pr_info.get("head_sha")
        if not head_sha:
            raise ValueError(f"PR #{pr_number} 无法获取 head_sha")

        # 2. 从 GitHub API 获取 CI check runs
        check_runs = await self._get_check_runs(head_sha)
        failing_runs = [r for r in check_runs if r.get("conclusion") == "failure"]

        # 3. 获取失败 Job 的详细日志
        failing_details = []
        for run in failing_runs[:3]:
            detail = await self._get_failing_job_details(run)
            failing_details.append(detail)

        # 4. 构建上下文
        context = self._build_context(pr_info, check_runs, failing_details)

        # 5. 获取 LLM 配置和系统提示词
        llm_config = await self._get_llm_config()
        system_prompt = self._get_system_prompt()

        # 6. 调用 LLM（120s 超时）
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
                max_tokens=8192,
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

    async def _get_pr_info(self, pr_number: int) -> dict:
        """获取 PR 信息：DB 优先，GitHub API 降级"""
        stmt = select(PullRequest).where(
            PullRequest.pr_number == pr_number,
            PullRequest.owner == settings.GITHUB_OWNER,
            PullRequest.repo == settings.GITHUB_REPO,
        )
        result = await self.db.execute(stmt)
        pr = result.scalar_one_or_none()

        if pr:
            return {
                "pr_number": pr.pr_number,
                "title": pr.title,
                "author": pr.author,
                "state": pr.state,
                "head_sha": pr.head_sha,
                "head_branch": pr.head_branch,
                "base_branch": pr.base_branch,
                "labels": pr.labels or [],
                "additions": pr.additions,
                "deletions": pr.deletions,
                "changed_files": pr.changed_files,
                "html_url": pr.html_url,
                "is_draft": pr.is_draft,
                "pipeline_stage": pr.pipeline_stage,
                "review_status": pr.review_status,
                "ci_status": pr.ci_status,
            }

        logger.info(f"PR #{pr_number} not in DB, fetching from GitHub API")
        client = self._get_github_client()
        pr_data = await client.get_pr_detail(settings.GITHUB_OWNER, settings.GITHUB_REPO, pr_number)
        return {
            "pr_number": pr_number,
            "title": pr_data.get("title", ""),
            "author": pr_data.get("user", {}).get("login", ""),
            "state": pr_data.get("state", ""),
            "head_sha": pr_data.get("head", {}).get("sha", ""),
            "head_branch": pr_data.get("head", {}).get("ref", ""),
            "base_branch": pr_data.get("base", {}).get("ref", ""),
            "labels": [l.get("name", "") for l in pr_data.get("labels", [])],
            "additions": pr_data.get("additions", 0),
            "deletions": pr_data.get("deletions", 0),
            "changed_files": pr_data.get("changed_files", 0),
            "html_url": pr_data.get("html_url", ""),
            "is_draft": pr_data.get("draft", False),
        }

    async def _get_check_runs(self, head_sha: str) -> list:
        """从 GitHub API 获取 CI check runs"""
        try:
            client = self._get_github_client()
            runs = await client.get_check_runs_for_sha(
                settings.GITHUB_OWNER, settings.GITHUB_REPO, head_sha
            )
            logger.info(f"Got {len(runs)} check runs for SHA {head_sha[:8]}")
            return runs
        except Exception as e:
            logger.warning(f"Failed to fetch check runs from GitHub API: {e}")
            return []

    async def _get_failing_job_details(self, check_run: dict) -> dict:
        """获取失败 check run 的 Job 详情和日志"""
        run_id = check_run.get("run_id")
        check_name = check_run.get("name", "N/A")
        check_url = check_run.get("html_url", "")

        if not run_id:
            return {"check_name": check_name, "url": check_url, "failing_jobs": []}

        try:
            client = self._get_github_client()
            jobs = await client.get_job_list(run_id)
            failing_jobs = [j for j in jobs if j.get("conclusion") == "failure"]

            job_details = []
            for job in failing_jobs[:3]:
                job_id = job.get("id")
                job_name = job.get("name", "N/A")
                runner_name = job.get("runner_name", "N/A")

                failed_steps = [
                    s.get("name", "N/A")
                    for s in job.get("steps", [])
                    if s.get("conclusion") == "failure"
                ]

                log_excerpt = ""
                if job_id:
                    try:
                        logs = await client.get_job_logs(job_id)
                        log_excerpt = self._extract_errors_from_logs(logs)
                    except Exception as e:
                        logger.warning(f"Failed to fetch logs for job {job_id}: {e}")
                        log_excerpt = ""

                job_details.append({
                    "job_name": job_name,
                    "runner_name": runner_name,
                    "failed_steps": failed_steps,
                    "log_excerpt": log_excerpt,
                })

            return {
                "check_name": check_name,
                "url": check_url,
                "conclusion": check_run.get("conclusion", ""),
                "failing_jobs": job_details,
            }
        except Exception as e:
            logger.warning(f"Failed to get job details for run {run_id}: {e}")
            return {"check_name": check_name, "url": check_url, "failing_jobs": [], "error": str(e)}

    def _extract_errors_from_logs(self, logs: str) -> str:
        """从 CI 日志中提取错误相关的行"""
        if not logs:
            return ""

        lines = logs.split("\n")
        error_patterns = [
            "FAILED", "##[error]", "Traceback", "AttributeError", "AssertionError",
            "TypeError", "ValueError", "KeyError", "exit code", "short test summary",
            "failed,", "FAILED TEST LOGS", "Process completed",
            "Executing the custom container",
        ]
        error_lines = []
        seen = set()

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue

            if any(p in stripped for p in error_patterns):
                start = max(0, i - 2)
                end = min(len(lines), i + 8)
                for j in range(start, end):
                    l = lines[j].strip()
                    if l and l not in seen:
                        seen.add(l)
                        error_lines.append(l[:500])

        result = "\n".join(error_lines[:80])
        return result[:10000]

    def _build_context(self, pr: dict, check_runs: list, failing_details: list) -> str:
        """构建 LLM 上下文 — 包含 PR 信息、CI 结果、失败详情、标签分析"""
        lines = [
            f"## PR #{pr.get('pr_number')} CI 失败诊断请求",
            "",
            "### PR 基本信息",
            f"- 标题: {pr.get('title', 'N/A')}",
            f"- 作者: {pr.get('author', 'N/A')}",
            f"- 状态: {pr.get('state', 'N/A')}" + (" (Draft)" if pr.get('is_draft') else ""),
            f"- 分支: {pr.get('head_branch', 'N/A')} → {pr.get('base_branch', 'N/A')}",
            f"- 代码变更: +{pr.get('additions', 0)} -{pr.get('deletions', 0)} ({pr.get('changed_files', 0)} 文件)",
            f"- Head SHA: {pr.get('head_sha', 'N/A')[:12]}",
            f"- PR URL: {pr.get('html_url', 'N/A')}",
        ]

        labels = pr.get("labels", [])
        if labels:
            lines.append(f"- 标签: {', '.join(labels)}")
            skip_labels = [l for l in labels if "skip" in l.lower()]
            if skip_labels:
                lines.append(f"  ⚠️ 注意：PR 包含 skip 相关标签: {', '.join(skip_labels)}，"
                             f"可能影响 CI 测试范围，需分析是否因此导致非预期测试运行或失败")
        else:
            lines.append("- 标签: 无")

        if pr.get("pipeline_stage"):
            lines.append(f"- Pipeline 阶段: {pr.get('pipeline_stage')}")
        if pr.get("review_status"):
            lines.append(f"- Review 状态: {pr.get('review_status')}")

        lines.append("")

        # CI check runs 汇总
        total = len(check_runs)
        passed = sum(1 for r in check_runs if r.get("conclusion") == "success")
        failed = sum(1 for r in check_runs if r.get("conclusion") == "failure")
        skipped = sum(1 for r in check_runs if r.get("conclusion") in ("skipped", "neutral"))
        lines.append(f"### CI Check 汇总（共 {total} 个，✅ {passed} 通过 / ❌ {failed} 失败 / ⏭️ {skipped} 跳过）")
        for run in check_runs[:15]:
            conclusion = run.get("conclusion", "N/A")
            icon = {"success": "✅", "failure": "❌", "skipped": "⏭️", "neutral": "➖"}.get(conclusion, "❓")
            lines.append(f"- {icon} {run.get('name', 'N/A')}: {conclusion}")

        # 失败详情
        if failing_details:
            lines.append(f"\n### 失败详情（{len(failing_details)} 个失败 Check）")
            for detail in failing_details:
                lines.append(f"\n#### {detail.get('check_name', 'N/A')}")
                if detail.get("url"):
                    lines.append(f"- Check URL: {detail.get('url')}")
                if detail.get("error"):
                    lines.append(f"- 获取详情失败: {detail.get('error')}")

                for job in detail.get("failing_jobs", []):
                    lines.append(f"\n**Job: {job.get('job_name', 'N/A')}**")
                    lines.append(f"- Runner: {job.get('runner_name', 'N/A')}")
                    if job.get("failed_steps"):
                        lines.append(f"- 失败步骤: {', '.join(job['failed_steps'])}")
                    if job.get("log_excerpt"):
                        lines.append("- 关键日志摘录:")
                        lines.append("```")
                        lines.append(job["log_excerpt"])
                        lines.append("```")
        else:
            lines.append("\n### 失败详情: 未获取到失败的 CI Job 信息")

        lines.append("")
        lines.append("请根据以上信息，运用根因分析方法论进行诊断，重点关注：")
        lines.append("1. 失败的测试是否与 PR 自身改动相关，还是 main 分支预存问题")
        lines.append("2. PR 标签（特别是 skip 相关标签）是否影响了 CI 测试范围，导致非预期行为")
        lines.append("3. 失败的根因链路：从错误现象 → 日志证据 → 根因定位")
        lines.append("4. 是否存在跨 PR 依赖问题（如其他 PR 的变更影响了当前 PR 的 CI）")
        lines.append("5. 给出明确的修复建议和优先级")

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
