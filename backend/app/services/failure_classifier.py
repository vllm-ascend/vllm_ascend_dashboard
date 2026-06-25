import logging
from typing import Any

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import JobFailureAnalysis, CIJob
from app.models.test_board import TestRun

logger = logging.getLogger(__name__)

CATEGORY_MAP = {
    "基础设施": "infrastructure",
    "测试用例": "test_bug",
    "开发代码": "product_bug",
    "其他": "unknown",
}


class FailureClassifier:
    async def classify(self, test_run: TestRun, ci_job: CIJob | None = None, db: AsyncSession | None = None) -> tuple[str, float]:
        if ci_job and db:
            analysis = await self._get_failure_analysis(ci_job.job_id, db)
            if analysis and analysis.problem_category:
                mapped = CATEGORY_MAP.get(analysis.problem_category, "unknown")
                return mapped, 0.7

        if ci_job:
            if self._is_infrastructure_failure(ci_job):
                return "infrastructure", 0.8
            if ci_job.conclusion == "cancelled":
                return "infrastructure", 0.7

        if test_run and test_run.result == "failed":
            return "unknown", 0.0

        return "unknown", 0.0

    async def _get_failure_analysis(self, job_id: int, db: AsyncSession) -> JobFailureAnalysis | None:
        stmt = select(JobFailureAnalysis).where(JobFailureAnalysis.job_id == job_id).limit(1)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    def _is_infrastructure_failure(self, ci_job: CIJob) -> bool:
        try:
            import json
            steps = json.loads(ci_job.steps_data) if ci_job.steps_data else []
            for step in steps:
                conclusion = step.get("conclusion", "")
                name = step.get("name", "").lower()
                if conclusion in ("timed_out", "startup_failure"):
                    return True
                if conclusion == "failure" and any(kw in name for kw in ("setup", "install", "checkout", "cache", "runner", "environment", "docker", "pip install", "build wheel")):
                    return True
        except (json.JSONDecodeError, TypeError):
            pass

        if ci_job.conclusion == "timed_out":
            return True

        job_name = ci_job.job_name.lower()
        infra_keywords = ("setup", "build", "install", "checkout", "environment", "runner", "infra", "deploy", "image", "pull")
        return any(kw in job_name for kw in infra_keywords)
