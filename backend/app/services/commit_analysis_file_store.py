import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.schemas.commit_analysis import CommitAnalysisStatus

PROJECT_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
SHA_PATTERN = re.compile(r"^[a-fA-F0-9]{7,64}$")


class CommitAnalysisFileStore:
    def __init__(self, base_dir: Path | None = None):
        if base_dir is None:
            base_dir = Path(settings.DATA_DIR) / "commit-analysis"
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _validate_project(self, project: str) -> None:
        if not PROJECT_PATTERN.fullmatch(project):
            raise ValueError("Invalid project")

    def _validate_sha(self, sha: str) -> None:
        if not SHA_PATTERN.fullmatch(sha):
            raise ValueError("Invalid sha")

    def _get_project_dir(self, project: str) -> Path:
        self._validate_project(project)
        project_dir = self.base_dir / project
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir

    def _get_analysis_path(self, project: str, sha: str) -> Path:
        self._validate_sha(sha)
        return self._get_project_dir(project) / f"{sha.lower()}.json"

    def empty_analysis(self, project: str, sha: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "project": project,
            "sha": sha,
            "assignee": None,
            "what_commit_did": None,
            "change_type": None,
            "affects_api": None,
            "vllm_ascend_impact": None,
            "next_plan": None,
            "planned_closure_time": None,
            "actual_closure_time": None,
            "ai_summary_markdown": None,
            "ai_summary_status": "not_generated",
            "ai_summary_generated_at": None,
            "ai_summary_generated_by": None,
            "ai_summary_llm_provider": None,
            "ai_summary_llm_model": None,
            "ai_summary_prompt_tokens": None,
            "ai_summary_completion_tokens": None,
            "ai_summary_generation_time_seconds": None,
            "ai_summary_error_message": None,
            "created_at": None,
            "created_by": None,
            "updated_at": None,
            "updated_by": None,
        }

    async def load_analysis(self, project: str, sha: str) -> dict[str, Any]:
        path = self._get_analysis_path(project, sha)
        if not path.exists():
            return self.empty_analysis(project, sha)

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {**self.empty_analysis(project, sha), **data, "project": project, "sha": sha}

    async def save_analysis(self, project: str, sha: str, data: dict[str, Any]) -> dict[str, Any]:
        path = self._get_analysis_path(project, sha)
        payload = {**self.empty_analysis(project, sha), **data, "project": project, "sha": sha}
        temp_path = path.with_suffix(".tmp")

        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        temp_path.rename(path)
        return payload

    async def load_batch(self, project: str, shas: list[str]) -> dict[str, dict[str, Any]]:
        analyses = {}
        for sha in shas:
            analyses[sha] = await self.load_analysis(project, sha)
        return analyses

    def derive_status(self, analysis: dict[str, Any]) -> CommitAnalysisStatus:
        if analysis.get("actual_closure_time"):
            return CommitAnalysisStatus.CLOSED

        has_core_fields = (
            bool(analysis.get("what_commit_did"))
            and bool(analysis.get("change_type"))
            and analysis.get("affects_api") is not None
            and bool(analysis.get("vllm_ascend_impact"))
        )
        if has_core_fields:
            return CommitAnalysisStatus.ANALYZED
        return CommitAnalysisStatus.NOT_ANALYZED

    def now(self) -> str:
        return datetime.now().astimezone().isoformat()
