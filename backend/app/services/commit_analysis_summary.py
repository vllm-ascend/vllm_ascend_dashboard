import json
import logging
import os
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ProjectDashboardConfig
from app.models.daily_summary import LLMProviderConfig
from app.services.claude_code_cli import run_with_fallback
from app.services.commit_analysis_file_store import CommitAnalysisFileStore
from app.services.daily_data_file_store import DailyDataFileStore

logger = logging.getLogger(__name__)


class CommitAnalysisSummaryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.analysis_store = CommitAnalysisFileStore()
        self.daily_store = DailyDataFileStore()

    async def generate_summary(
        self,
        project: str,
        sha: str,
        username: str,
        data_date: date | None = None,
        llm_provider: str | None = None,
    ) -> dict[str, Any]:
        analysis = await self.analysis_store.load_analysis(project, sha)

        try:
            commit = await self._find_commit(project, sha, data_date)
            prompt = self._build_prompt(project, sha, commit, analysis)
            llm_config = await self._get_llm_config(llm_provider)
            system_prompt = await self._get_system_prompt(project)

            provider_config = {
                "provider": llm_config.provider,
                "api_key": llm_config.decrypted_api_key,
                "api_base_url": llm_config.api_base_url,
                "default_model": llm_config.default_model,
            }

            if os.environ.get("AGENT_SERVICE_ENABLED", "").lower() in ("1", "true", "yes"):
                from app.services.agent_service import AgentService, AgentTask

                agent_svc = AgentService(self.db)
                agent_result = await agent_svc.run(AgentTask(
                    prompt=prompt,
                    provider_config=provider_config,
                    system_prompt=system_prompt,
                    max_steps=5,
                    memory_type="commit_analysis",
                    memory_filters={"project": project},
                ))
                if agent_result.exit_code != 0:
                    raise RuntimeError(f"Agent generation failed: {agent_result.error_message}")
                ai_summary_markdown = agent_result.content
                ai_model_used = agent_result.model_used or llm_config.default_model
                ai_generation_time = int(agent_result.duration_seconds)
            else:
                result = await run_with_fallback(
                    prompt=prompt,
                    provider_config=provider_config,
                    system_prompt=system_prompt,
                    max_turns=5,
                )
                ai_summary_markdown = result.content
                ai_model_used = result.model_used or llm_config.default_model
                ai_generation_time = int(result.duration_seconds)

            now = self.analysis_store.now()
            analysis.update({
                "ai_summary_markdown": ai_summary_markdown,
                "ai_summary_status": "success",
                "ai_summary_generated_at": now,
                "ai_summary_generated_by": username,
                "ai_summary_llm_provider": llm_config.provider,
                "ai_summary_llm_model": ai_model_used,
                "ai_summary_prompt_tokens": None,  # CLI 模式下不可用
                "ai_summary_completion_tokens": None,
                "ai_summary_generation_time_seconds": ai_generation_time,
                "ai_summary_error_message": None,
                "updated_at": now,
                "updated_by": username,
            })
            return await self.analysis_store.save_analysis(project, sha, analysis)
        except Exception as e:
            logger.error("Failed to generate commit AI summary: %s", e)
            now = self.analysis_store.now()
            analysis.update({
                "ai_summary_status": "failed",
                "ai_summary_error_message": str(e),
                "updated_at": now,
                "updated_by": username,
            })
            await self.analysis_store.save_analysis(project, sha, analysis)
            raise

    async def _find_commit(self, project: str, sha: str, data_date: date | None) -> dict[str, Any] | None:
        if data_date:
            commit = await self._find_commit_in_date(project, sha, data_date)
            if commit:
                return commit

        for date_str in await self.daily_store.list_available_dates(project, limit=100):
            try:
                commit = await self._find_commit_in_date(project, sha, date.fromisoformat(date_str))
            except ValueError:
                continue
            if commit:
                return commit
        return None

    async def _find_commit_in_date(self, project: str, sha: str, data_date: date) -> dict[str, Any] | None:
        data = await self.daily_store.load_daily_data(project, data_date)
        if not data:
            return None
        sha_lower = sha.lower()
        for commit in data.get("commits", []):
            if str(commit.get("sha", "")).lower() == sha_lower:
                return commit
        return None

    async def _get_llm_config(self, provider: str | None = None) -> LLMProviderConfig:
        stmt = select(LLMProviderConfig)
        if provider:
            stmt = stmt.where(LLMProviderConfig.provider == provider)
        else:
            stmt = stmt.where(LLMProviderConfig.is_active == True)

        result = await self.db.execute(stmt.limit(1))
        config = result.scalar_one_or_none()
        if not config:
            raise ValueError("No active LLM provider configured. Please set a provider as 'is_active' in the LLM Provider Config page.")
        if not config.api_key:
            raise ValueError(f"API Key not configured for provider: {config.provider}. Please configure API Key in the LLM Provider Config page.")
        return config

    async def _get_system_prompt(self, project: str) -> str:
        stmt = select(ProjectDashboardConfig).where(
            ProjectDashboardConfig.config_key == "commit_analysis_system_prompt"
        )
        result = await self.db.execute(stmt)
        config = result.scalar_one_or_none()
        if config and config.config_value:
            prompt = config.config_value.get(project)
            if prompt:
                return prompt
        return self._default_system_prompt(project)

    def _default_system_prompt(self, project: str) -> str:
        project_name = "vLLM" if project == "vllm" else "vLLM Ascend"
        return f"""你是一名专业的 {project_name} Commit 技术分析师。请基于给定的 Commit 元信息、关联 PR 信息、文件变更和已有人工分析字段，生成中文 Markdown 总结。

要求：
1. 概括该 Commit 做了什么
2. 判断修改类型：Feature / Bugfix / Refactor / Common / Test / CI / Other
3. 判断是否影响 API，并说明原因
4. 分析对 vLLM Ascend 的潜在影响；如不涉及，请明确说明“不涉及”
5. 给出后续跟进建议；如无需跟进，请明确说明“不涉及”
6. 输出结构清晰，避免编造未提供的信息"""

    def _build_prompt(self, project: str, sha: str, commit: dict[str, Any] | None, analysis: dict[str, Any]) -> str:
        commit_context = self._format_commit_context(commit) if commit else "未在每日数据中找到该 Commit 的详细元信息，请仅基于 SHA 和已有人工分析字段总结。"
        analysis_context = {
            "what_commit_did": analysis.get("what_commit_did"),
            "change_type": analysis.get("change_type"),
            "affects_api": analysis.get("affects_api"),
            "vllm_ascend_impact": analysis.get("vllm_ascend_impact"),
            "next_plan": analysis.get("next_plan"),
            "planned_closure_time": analysis.get("planned_closure_time"),
            "actual_closure_time": analysis.get("actual_closure_time"),
        }
        return f"""项目：{project}
SHA：{sha}

## Commit 上下文
{commit_context}

## 已有人工分析字段
```json
{json.dumps(analysis_context, ensure_ascii=False, indent=2)}
```

请输出 Markdown，总结该 Commit 的技术含义、风险、对 vLLM Ascend 的影响和下一步建议。"""

    def _format_commit_context(self, commit: dict[str, Any]) -> str:
        context = {
            "sha": commit.get("sha"),
            "message": self._truncate(commit.get("message"), 1000),
            "full_message": self._truncate(commit.get("full_message"), 2000),
            "author": commit.get("author"),
            "author_email": commit.get("author_email"),
            "committed_at": commit.get("committed_at"),
            "html_url": commit.get("html_url"),
            "pr_number": commit.get("pr_number"),
            "pr_title": commit.get("pr_title"),
            "pr_description": self._truncate(commit.get("pr_description"), 3000),
            "files_changed": commit.get("files_changed", [])[:50],
            "additions": commit.get("additions"),
            "deletions": commit.get("deletions"),
        }
        return f"```json\n{json.dumps(context, ensure_ascii=False, indent=2, default=self._json_default)}\n```"

    def _truncate(self, value: Any, max_length: int) -> Any:
        if not isinstance(value, str) or len(value) <= max_length:
            return value
        return f"{value[:max_length]}..."

    def _json_default(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)
