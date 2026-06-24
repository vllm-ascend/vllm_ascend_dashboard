import logging
import time
import asyncio
from typing import AsyncGenerator, Optional

from sqlalchemy import select, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CIJob, CIResult, ProjectDashboardConfig
from app.models.daily_summary import LLMProviderConfig
from app.services.llm_client import LLMClient, LLMError
from app.services.skill_registry import get_skill_registry

logger = logging.getLogger(__name__)


class IssueDiagnosisService:

    def __init__(self):
        self.llm_client = LLMClient()

    async def _get_llm_config(self, db: AsyncSession) -> LLMProviderConfig:
        stmt = select(LLMProviderConfig).where(LLMProviderConfig.is_active == True).limit(1)
        result = await db.execute(stmt)
        config = result.scalar_one_or_none()
        if not config:
            raise ValueError("No active LLM provider configured")
        if not config.api_key:
            raise ValueError(f"API Key not configured for provider: {config.provider}")
        return config

    async def _get_system_prompt(self, data_source_type: str, db: AsyncSession) -> str:
        if data_source_type == "ci_job":
            config_key = "ci_failure_analysis_system_prompt"
        elif data_source_type == "commit":
            config_key = "commit_analysis_system_prompt"
        else:
            config_key = "general_diagnosis_system_prompt"

        stmt = select(ProjectDashboardConfig).where(
            ProjectDashboardConfig.config_key == config_key
        )
        result = await db.execute(stmt)
        config = result.scalar_one_or_none()
        if config and config.config_value:
            value = config.config_value
            if isinstance(value, dict):
                return value.get('default', self._get_skill_prompt(data_source_type))
            if isinstance(value, str):
                return value

        return self._get_skill_prompt(data_source_type)

    def _get_skill_prompt(self, data_source_type: str) -> str:
        registry = get_skill_registry()
        if data_source_type == "ci_job":
            skill = registry.get_skill_by_scope("ci_failure_analysis")
            if skill and skill.content:
                return skill.content
            return "你是一名专业的 CI/CD 失败诊断分析师。请根据提供的 CI Job 失败信息，进行根因分析并给出改进建议。"
        if data_source_type == "commit":
            skill = registry.get_skill_by_scope("commit_analysis")
            if skill and skill.content:
                return skill.content
            return "你是一名专业的代码分析专家。请根据提供的 commit 信息，分析代码变更的影响和潜在问题。"
        return "你是一名专业的技术问题诊断专家。请根据提供的信息，进行深入分析并给出诊断结论和建议。"

    async def _collect_ci_job_context(self, job_id: int, db: AsyncSession) -> str:
        stmt = select(CIJob).where(CIJob.job_id == job_id)
        result = await db.execute(stmt)
        job = result.scalar_one_or_none()
        if not job:
            raise ValueError(f"CIJob with job_id={job_id} not found")

        from app.services.failure_analysis import FailureAnalysisService
        fa_service = FailureAnalysisService()
        context = await fa_service._build_job_context(job, db)
        return context

    async def _collect_commit_context(
        self,
        run_id: Optional[int],
        commit_sha: Optional[str],
        db: AsyncSession,
    ) -> str:
        lines = ["## Commit 分析上下文\n"]

        if run_id:
            stmt = select(CIResult).where(CIResult.run_id == run_id).limit(1)
            result = await db.execute(stmt)
            ci_result = result.scalar_one_or_none()
            if ci_result:
                lines.append(f"- **Workflow**: {ci_result.workflow_name}")
                lines.append(f"- **Run Number**: #{ci_result.run_number}")
                lines.append(f"- **Head SHA**: {ci_result.head_sha}")
                lines.append(f"- **结论**: {ci_result.conclusion}")
                lines.append(f"- **分支**: {ci_result.branch}")
                lines.append("")
                lines.append("> 注意：当前版本仅提供 CI Run 元信息作为上下文，暂不支持获取 commit diff。如需完整 commit 分析，请在提示词中补充 commit 详情或日志内容。")

        if commit_sha:
            lines.append(f"- **指定 Commit SHA**: {commit_sha}")

        return "\n".join(lines)

    async def stream_diagnose(
        self,
        data_source_type: str,
        job_id: Optional[int],
        run_id: Optional[int],
        commit_sha: Optional[str],
        user_prompt: Optional[str],
        db: AsyncSession,
    ) -> AsyncGenerator[dict, None]:
        try:
            llm_config = await self._get_llm_config(db)

            effective_type = data_source_type
            if data_source_type == "ci_job" and not job_id and not user_prompt:
                raise ValueError("ci_job requires job_id or user_prompt")
            if data_source_type == "ci_job" and not job_id:
                effective_type = "manual"

            system_prompt = await self._get_system_prompt(effective_type, db)

            context = ""
            if data_source_type == "ci_job" and job_id:
                context = await self._collect_ci_job_context(job_id, db)
            elif data_source_type == "commit":
                context = await self._collect_commit_context(run_id, commit_sha, db)
            elif effective_type == "manual":
                context = ""

            full_user_prompt = context
            if user_prompt:
                if context:
                    full_user_prompt = f"{context}\n\n### 用户补充提示词\n{user_prompt}"
                else:
                    full_user_prompt = user_prompt

            if not full_user_prompt:
                raise ValueError("No context or prompt provided for diagnosis")

            yield {
                "event": "meta",
                "data": {
                    "provider": llm_config.provider,
                    "model": llm_config.default_model,
                }
            }

            start_time = time.time()
            total_content = ""
            chunk_count = 0

            try:
                stream_gen = self.llm_client.generate_stream(
                    provider=llm_config.provider,
                    model=llm_config.default_model,
                    api_key=llm_config.api_key,
                    api_base=llm_config.api_base_url,
                    system_prompt=system_prompt,
                    user_prompt=full_user_prompt,
                    temperature=0.3,
                    max_tokens=8192,
                )
                first_chunk_timeout = 60
                chunk_timeout = 30
                got_first_chunk = False

                async for chunk in stream_gen:
                    got_first_chunk = True
                    total_content += chunk
                    chunk_count += 1
                    yield {
                        "event": "chunk",
                        "data": {"content": chunk}
                    }

                if not got_first_chunk:
                    raise LLMError("LLM stream produced no output (possible timeout)")

                duration = time.time() - start_time
                yield {
                    "event": "done",
                    "data": {
                        "total_content_length": len(total_content),
                        "duration_seconds": round(duration, 1),
                        "chunk_count": chunk_count,
                    }
                }
            except LLMError as e:
                yield {
                    "event": "error",
                    "data": {"message": str(e)}
                }
        except ValueError as e:
            yield {
                "event": "error",
                "data": {"message": str(e)}
            }
        except Exception as e:
            yield {
                "event": "error",
                "data": {"message": f"内部错误: {str(e)}"}
            }

    async def get_failed_ci_jobs(self, days_back: int, db: AsyncSession) -> list[dict]:
        from datetime import datetime, timedelta, UTC

        cutoff = datetime.now(UTC) - timedelta(days=days_back)
        stmt = select(CIJob).where(
            and_(
                CIJob.conclusion == "failure",
                CIJob.completed_at >= cutoff,
            )
        ).order_by(desc(CIJob.completed_at)).limit(100)
        result = await db.execute(stmt)
        jobs = result.scalars().all()

        return [
            {
                "job_id": j.job_id,
                "run_id": j.run_id,
                "workflow_name": j.workflow_name,
                "job_name": j.job_name,
                "conclusion": j.conclusion,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            }
            for j in jobs
        ]

    async def get_recent_commits(self, days_back: int, db: AsyncSession) -> list[dict]:
        from datetime import datetime, timedelta, UTC

        cutoff = datetime.now(UTC) - timedelta(days=days_back)
        stmt = select(CIResult).where(
            CIResult.completed_at >= cutoff,
        ).order_by(desc(CIResult.completed_at)).limit(50)
        result = await db.execute(stmt)
        runs = result.scalars().all()

        return [
            {
                "sha": r.head_sha,
                "message": r.head_sha,
                "committed_at": r.completed_at.isoformat() if r.completed_at else None,
                "run_id": r.run_id,
                "run_number": r.run_number,
            }
            for r in runs
        ]
