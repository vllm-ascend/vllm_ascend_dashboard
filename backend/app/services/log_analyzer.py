"""
CI 失败 Job 日志分析服务

利用 Claude Code CLI 的多步推理 + 工具调用能力，
自动化分析 CI 失败的原因。CLI 可以：
1. 通过 curl 获取 GitHub Actions 的失败日志
2. 搜索 git log 对比本次与上次成功的差异
3. 搜索代码库中相关的错误信息定位根因
4. 输出结构化的分析结果（根因分类 + 建议修复方案）
"""
import json
import logging
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import CIJob, CIResult
from app.services.claude_code_cli import ClaudeCodeCLI, run_with_fallback

logger = logging.getLogger(__name__)

# 根因分类枚举
ROOT_CAUSE_CATEGORIES = [
    "code_bug",        # 代码缺陷
    "env_issue",       # 环境问题（依赖缺失、版本不兼容）
    "timeout",         # 超时
    "flaky_test",      # 不稳定测试
    "dependency",      # 外部依赖变更
    "infra",           # 基础设施问题（runner/网络）
    "config_error",    # CI 配置错误
    "unknown",         # 无法确定
]

ANALYSIS_SYSTEM_PROMPT = """你是一名资深的 CI/CD 和 vLLM 项目工程师。你的任务是分析 CI 失败 job 的日志，
找出根本原因，并提供可操作的修复建议。

分析步骤：
1. 仔细阅读提供的日志和上下文信息
2. 识别具体的错误信息和类型
3. 判断根因分类（从以下选项中选择）：
   - code_bug: 代码逻辑缺陷
   - env_issue: 环境问题（依赖缺失、版本不兼容、硬件问题）
   - timeout: 执行超时
   - flaky_test: 不稳定测试（间歇性失败）
   - dependency: 外部依赖变更
   - infra: 基础设施问题（runner 资源不足、网络故障）
   - config_error: CI 配置错误
   - unknown: 无法确定
4. 提供详细的根因分析（Markdown 格式）
5. 给出建议的修复方案
6. 如果可能，指出相关的代码文件或 commit

输出格式：
```json
{
  "root_cause_category": "code_bug",
  "analysis_markdown": "...",
  "suggested_fix": "...",
  "related_files": ["path/to/file.py"],
  "related_commits": ["abc123"],
  "confidence": "high"
}
```"""


class LogAnalyzer:
    """CI 失败日志分析器"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def analyze_failed_job(
        self,
        job: CIJob,
        provider_config: dict | None = None,
    ) -> dict:
        """
        分析单个失败的 CI job。

        Args:
            job: 失败的 CIJob 实例
            provider_config: LLM provider 配置（None 则从 DB 读取 active）

        Returns:
            分析结果 dict，包含 root_cause_category, analysis_markdown 等
        """
        if provider_config is None:
            provider_config = await self._get_active_provider_config()

        # 1. 收集上下文
        context = await self._build_job_context(job)

        # 2. 构建 prompt
        prompt = self._build_analysis_prompt(job, context)

        # 3. 调用 Claude Code CLI（让 CLI 自己 fetch 日志 URL）
        try:
            result = await run_with_fallback(
                prompt=prompt,
                provider_config=provider_config,
                system_prompt=ANALYSIS_SYSTEM_PROMPT,
                max_turns=10,
            )
        except Exception as e:
            logger.error(f"Log analysis failed for job {job.job_id}: {e}")
            return {
                "root_cause_category": "unknown",
                "analysis_markdown": f"分析失败: {e}",
                "suggested_fix": "",
                "related_files": [],
                "related_commits": [],
                "confidence": "low",
                "error": str(e),
                "analyzed_at": datetime.now(UTC).isoformat(),
            }

        # 4. 解析结果
        analysis = self._parse_analysis_result(result.content)
        analysis["analyzed_at"] = datetime.now(UTC).isoformat()
        analysis["claude_duration_seconds"] = int(result.duration_seconds)
        analysis["claude_model_used"] = result.model_used

        return analysis

    async def analyze_failed_jobs_batch(
        self,
        provider_config: dict | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        批量分析最近失败的、尚未分析的 CI jobs。

        Args:
            provider_config: LLM provider 配置
            limit: 最多分析多少个 job

        Returns:
            分析结果列表，每个元素为 {job_id, run_id, analysis: {...}}
        """
        if provider_config is None:
            provider_config = await self._get_active_provider_config()

        # 查找最近失败的、尚未分析的 jobs
        from app.models import CIFailureAnalysis

        # 子查询：已分析过的 job_id
        analyzed_subq = select(CIFailureAnalysis.job_id)

        stmt = (
            select(CIJob)
            .where(
                CIJob.conclusion.in_(["failure", "cancelled"]),
                CIJob.job_id.notin_(analyzed_subq),
            )
            .order_by(CIJob.completed_at.desc().nulls_last())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        failed_jobs = result.scalars().all()

        logger.info(f"Found {len(failed_jobs)} unanalyzed failed jobs")
        results = []

        for job in failed_jobs:
            try:
                analysis = await self.analyze_failed_job(job, provider_config)
                await self._save_analysis(job, analysis)
                results.append({
                    "job_id": job.job_id,
                    "run_id": job.run_id,
                    "analysis": analysis,
                })
            except Exception as e:
                logger.error(f"Failed to analyze job {job.job_id}: {e}")
                results.append({
                    "job_id": job.job_id,
                    "run_id": job.run_id,
                    "analysis": {
                        "root_cause_category": "unknown",
                        "analysis_markdown": f"分析失败: {e}",
                        "error": str(e),
                    },
                })

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_active_provider_config(self) -> dict:
        """获取当前激活的 LLM provider 配置"""
        from app.models.daily_summary import LLMProviderConfig

        stmt = select(LLMProviderConfig).where(LLMProviderConfig.is_active == True)
        result = await self.db.execute(stmt)
        config = result.scalar_one_or_none()

        if not config:
            raise ValueError(
                "No active LLM provider configured. "
                "Set a provider as active in System Config."
            )

        return {
            "provider": config.provider,
            "api_key": config.api_key or "",
            "api_base_url": config.api_base_url or "",
            "default_model": config.default_model,
        }

    async def _build_job_context(self, job: CIJob) -> dict:
        """收集 job 的上下文信息"""
        context = {
            "workflow_name": job.workflow_name,
            "job_name": job.job_name,
            "conclusion": job.conclusion,
            "hardware": job.hardware,
            "runner_name": job.runner_name,
            "duration_seconds": job.duration_seconds,
            "logs_url": job.logs_url,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }

        # 解析 steps_data
        if job.steps_data:
            try:
                steps = json.loads(job.steps_data)
                # 只保留失败或关键步骤
                context["failed_steps"] = [
                    s for s in steps
                    if s.get("conclusion") in ("failure", "cancelled")
                ]
                context["all_steps"] = steps
            except Exception:
                pass

        # 获取同 workflow 最近一次成功的 run
        try:
            stmt = (
                select(CIResult)
                .where(
                    CIResult.workflow_name == job.workflow_name,
                    CIResult.conclusion == "success",
                )
                .order_by(CIResult.completed_at.desc())
                .limit(1)
            )
            result = await self.db.execute(stmt)
            last_success = result.scalar_one_or_none()
            if last_success:
                context["last_successful_run"] = {
                    "run_id": last_success.run_id,
                    "run_number": last_success.run_number,
                    "completed_at": last_success.completed_at.isoformat() if last_success.completed_at else None,
                    "head_sha": last_success.head_sha,
                }
        except Exception as e:
            logger.warning(f"Failed to find last successful run: {e}")

        # 获取相关的 recent commits (limit 5)
        try:
            stmt = (
                select(CIResult.head_sha)
                .where(
                    CIResult.workflow_name == job.workflow_name,
                    CIResult.head_sha.isnot(None),
                )
                .order_by(CIResult.completed_at.desc())
                .limit(5)
            )
            result = await self.db.execute(stmt)
            shas = [row[0] for row in result.all()]
            context["recent_commits"] = shas
        except Exception as e:
            logger.warning(f"Failed to get recent commits: {e}")

        return context

    def _build_analysis_prompt(self, job: CIJob, context: dict) -> str:
        """构建分析 prompt"""
        owner = settings.GITHUB_OWNER
        repo = settings.GITHUB_REPO

        prompt_parts = [
            "请分析以下 CI 失败 job：",
            "",
            f"## Job 基本信息",
            f"- Workflow: {job.workflow_name}",
            f"- Job: {job.job_name}",
            f"- 结论: {job.conclusion}",
            f"- 硬件: {job.hardware}",
            f"- Runner: {job.runner_name}",
            f"- 耗时: {job.duration_seconds}s" if job.duration_seconds else "",
            f"- 日志 URL: {job.logs_url}" if job.logs_url else "",
            f"- GitHub Run: https://github.com/{owner}/{repo}/actions/runs/{job.run_id}",
        ]

        # 失败步骤
        failed_steps = context.get("failed_steps", [])
        if failed_steps:
            prompt_parts.append("")
            prompt_parts.append("## 失败步骤")
            for step in failed_steps:
                name = step.get("name", "Unknown")
                conclusion = step.get("conclusion", "?")
                prompt_parts.append(f"- {name}: {conclusion}")

        # 最近一次成功运行
        last_success = context.get("last_successful_run")
        if last_success:
            prompt_parts.append("")
            prompt_parts.append("## 最近一次成功运行")
            prompt_parts.append(f"- Run ID: {last_success.get('run_id')}")
            prompt_parts.append(f"- SHA: {last_success.get('head_sha')}")

        # 可用的 GitHub token（让 CLI 可以用它来 fetch 日志）
        if settings.GITHUB_TOKEN:
            prompt_parts.append("")
            prompt_parts.append(
                "你可以使用以下命令获取详细日志：\n"
                f'curl -H "Authorization: Bearer {settings.GITHUB_TOKEN}" '
                f'"{job.logs_url}" 2>/dev/null | head -500'
            )

        prompt_parts.append("")
        prompt_parts.append(
            "请按照 system prompt 中指定的 JSON 格式输出分析结果。"
            "请务必在该 JSON 之前用 ```json 和 ``` 包裹。"
        )

        return "\n".join(prompt_parts)

    def _parse_analysis_result(self, content: str) -> dict:
        """解析 AI 输出，提取结构化分析结果"""
        # 默认值
        result = {
            "root_cause_category": "unknown",
            "analysis_markdown": content,
            "suggested_fix": "",
            "related_files": [],
            "related_commits": [],
            "confidence": "medium",
        }

        # 尝试提取 JSON 块
        try:
            # 查找 ```json ... ``` 代码块
            json_start = content.find("```json")
            if json_start >= 0:
                json_start = content.find("\n", json_start) + 1
                json_end = content.find("```", json_start)
                if json_end > json_start:
                    json_str = content[json_start:json_end].strip()
                    parsed = json.loads(json_str)
                    if isinstance(parsed, dict):
                        result.update({
                            k: v for k, v in parsed.items()
                            if k in result
                        })
            else:
                # 尝试直接解析整个内容
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    result.update({
                        k: v for k, v in parsed.items()
                        if k in result
                    })
        except (json.JSONDecodeError, ValueError):
            logger.debug("Could not parse JSON from analysis result, using raw markdown")

        # 验证 root_cause_category
        if result["root_cause_category"] not in ROOT_CAUSE_CATEGORIES:
            result["root_cause_category"] = "unknown"

        return result

    async def _save_analysis(self, job: CIJob, analysis: dict) -> None:
        """保存分析结果到数据库"""
        from app.models import CIFailureAnalysis

        try:
            stmt = select(CIFailureAnalysis).where(
                CIFailureAnalysis.job_id == job.job_id
            )
            check_result = await self.db.execute(stmt)
            existing = check_result.scalar_one_or_none()

            if existing:
                # 更新已有记录
                existing.root_cause_category = analysis.get("root_cause_category", "unknown")
                existing.analysis_markdown = analysis.get("analysis_markdown", "")
                existing.suggested_fix = analysis.get("suggested_fix", "")
                existing.related_commits = analysis.get("related_commits", [])
                existing.confidence = analysis.get("confidence", "medium")
                existing.analyzed_at = datetime.now(UTC)
                if "claude_model_used" in analysis:
                    existing.claude_model_used = analysis["claude_model_used"]
                if "claude_duration_seconds" in analysis:
                    existing.claude_duration_seconds = analysis["claude_duration_seconds"]
            else:
                # 创建新记录
                new_analysis = CIFailureAnalysis(
                    job_id=job.job_id,
                    run_id=job.run_id,
                    workflow_name=job.workflow_name,
                    job_name=job.job_name,
                    root_cause_category=analysis.get("root_cause_category", "unknown"),
                    analysis_markdown=analysis.get("analysis_markdown", ""),
                    suggested_fix=analysis.get("suggested_fix", ""),
                    related_commits=analysis.get("related_commits", []),
                    confidence=analysis.get("confidence", "medium"),
                    claude_model_used=analysis.get("claude_model_used", ""),
                    claude_duration_seconds=analysis.get("claude_duration_seconds"),
                    analyzed_at=datetime.now(UTC),
                )
                self.db.add(new_analysis)

            await self.db.commit()
            logger.info(f"Analysis saved for job {job.job_id}")
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Failed to save analysis for job {job.job_id}: {e}")
            raise
