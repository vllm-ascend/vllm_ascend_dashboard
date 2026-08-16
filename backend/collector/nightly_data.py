"""Collect and materialize Nightly test data.

The Scheduler only creates a durable task.  Repository access and all writes
to ``nightly_test_cases``/``daily_failure_records`` belong to the Collector so
that the same workflow is valid in local, Linux, and horizontally scaled
deployments.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.clients.github_cache import get_github_cache_for_repo
from infrastructure.core.config import settings
from infrastructure.persistence.models import (
    CIJob,
    DailyFailureRecord,
    NightlyTestCase,
)
from tooling.parsers.nightly_config_parser import NightlyConfigParser, load_model_fo_map

logger = logging.getLogger(__name__)


class NightlyDataCollector:
    """Snapshot Nightly YAML and materialize failed Nightly jobs."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _get_parser(self) -> NightlyConfigParser:
        """Return a parser backed by the shared disposable Git cache.

        The cache is normally refreshed by the project-dashboard cache job.  A
        clone is still ensured here because this task must also work when it is
        the first Collector task executed after a clean deployment.
        """

        parser = NightlyConfigParser()
        if parser.is_available:
            return parser

        cache = get_github_cache_for_repo(settings.GITHUB_OWNER, settings.GITHUB_REPO)
        if not cache.clone():
            raise RuntimeError(
                "vllm-ascend repository cache is unavailable; "
                f"expected {cache.cache_dir}"
            )
        parser = NightlyConfigParser(repo_path=str(cache.cache_dir))
        if not parser.is_available:
            raise RuntimeError(f"nightly_config.yaml not found at {parser.config_file}")
        return parser

    async def sync(self) -> dict[str, int]:
        """Run both stages in dependency order and return row counts."""

        snapshot_count = await self.snapshot_configs()
        failure_count = await self.populate_daily_failure_records()
        return {
            "nightly_test_cases": snapshot_count,
            "daily_failure_records": failure_count,
        }

    async def snapshot_configs(self) -> int:
        """Snapshot active branches from ``nightly_config.yaml``."""

        parser = self._get_parser()
        fo_map = load_model_fo_map()
        today = date.today()
        branches = parser.get_active_branches()
        target_branches = ["main", *(b for b in branches if b.startswith("releases/"))]

        total = 0
        for branch in target_branches:
            if not parser.checkout_branch(branch):
                logger.warning("Unable to checkout Nightly config branch %s", branch)
                continue
            cases = parser.parse(report_date=today.isoformat(), source_branch=branch)
            for case in cases:
                result = await self.db.execute(
                    select(NightlyTestCase).where(
                        NightlyTestCase.report_date == today,
                        NightlyTestCase.source_branch == branch,
                        NightlyTestCase.workflow_name == case.workflow,
                        NightlyTestCase.job_name == case.name,
                    )
                )
                existing = result.scalar_one_or_none()
                model_fo = (
                    fo_map.get(case.model_path)
                    or fo_map.get(case.model_path.split("/")[-1])
                    or fo_map.get(
                        case.model_path.rsplit(".", 1)[0]
                        if "." in case.model_path
                        else case.model_path
                    )
                    or ""
                )
                if existing is None:
                    self.db.add(
                        NightlyTestCase(
                            report_date=today,
                            source_branch=branch,
                            workflow_name=case.workflow,
                            job_name=case.name,
                            display_name=case.name,
                            test_model=case.model_path,
                            model_fo=model_fo,
                            deployment_type=case.deployment,
                        )
                    )
                else:
                    existing.display_name = case.name
                    existing.test_model = case.model_path
                    existing.deployment_type = case.deployment
                    if model_fo:
                        existing.model_fo = model_fo
                total += 1

        if total:
            await self.db.commit()
        logger.info(
            "Nightly config snapshot completed: %d entries across %d branches",
            total,
            len(target_branches),
        )
        return total

    async def populate_daily_failure_records(self) -> int:
        """Materialize failed or cancelled Nightly jobs matched to YAML snapshots.

        Cancellation is not a test failure and is excluded from test-board
        execution results, but it is still an operational state that must be
        retained in DailyFailureTracking for follow-up.
        """

        beijing_tz = timezone(timedelta(hours=8))
        cutoff = datetime.now(UTC) - timedelta(days=14)

        result = await self.db.execute(
            select(CIJob).where(
                CIJob.started_at >= cutoff,
                CIJob.conclusion.in_(
                    ["failure", "timed_out", "startup_failure", "cancelled"]
                ),
            )
        )
        tracked_jobs = result.scalars().all()

        snapshot_result = await self.db.execute(select(NightlyTestCase))
        snapshots = snapshot_result.scalars().all()
        snapshot_map = {
            (
                str(case.report_date),
                case.source_branch,
                case.workflow_name,
                case.job_name,
            ): case
            for case in snapshots
        }
        # A fresh deployment only has today's snapshot, while the CI window
        # can contain failures from earlier dates. Exact-date snapshots win;
        # the fallback lets the first run backfill historical jobs.
        fallback_snapshots: dict[tuple[str, str], list[NightlyTestCase]] = {}
        for snapshot in snapshots:
            fallback_snapshots.setdefault(
                (snapshot.source_branch, snapshot.workflow_name),
                [],
            ).append(snapshot)
        for values in fallback_snapshots.values():
            values.sort(key=lambda item: str(item.report_date), reverse=True)

        existing_result = await self.db.execute(select(DailyFailureRecord))
        existing_keys = {
            (
                str(record.report_date),
                record.source_branch,
                record.workflow_name,
                record.job_name,
            )
            for record in existing_result.scalars().all()
        }

        branch_re = re.compile(r"^\S+\s+\(([^,]+),")
        new_count = 0
        for job in tracked_jobs:
            if not job.started_at:
                continue
            started = job.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=UTC)
            report_date = started.astimezone(beijing_tz).date().isoformat()
            branch_match = branch_re.match(job.job_name or "")
            branch = branch_match.group(1) if branch_match else "main"
            key = (report_date, branch, job.workflow_name, job.job_name)
            if key in existing_keys:
                continue

            snapshot = self._match_snapshot(
                snapshot_map,
                fallback_snapshots,
                report_date=report_date,
                source_branch=branch,
                workflow_name=job.workflow_name,
                job_name=job.job_name or "",
            )
            if snapshot is None:
                # This intentionally filters infrastructure jobs such as
                # ``Build image`` and ``Remove node taints``.
                continue

            github_url = (
                f"https://github.com/{settings.GITHUB_OWNER}/{settings.GITHUB_REPO}"
                f"/actions/runs/{job.run_id}/job/{job.job_id}"
                if job.job_id
                else None
            )
            self.db.add(
                DailyFailureRecord(
                    report_date=report_date,
                    source_branch=branch,
                    workflow_name=job.workflow_name,
                    job_name=job.job_name,
                    run_id=job.run_id,
                    job_id=job.job_id,
                    conclusion=job.conclusion,
                    started_at=job.started_at,
                    completed_at=job.completed_at,
                    duration_seconds=job.duration_seconds,
                    hardware=job.hardware,
                    display_name=snapshot.display_name,
                    test_model=snapshot.test_model,
                    model_fo=snapshot.model_fo,
                    owner=snapshot.owner,
                    deployment_type=snapshot.deployment_type,
                    processing_status="未处理",
                    github_job_url=github_url,
                )
            )
            existing_keys.add(key)
            new_count += 1

        if new_count:
            await self.db.commit()
        logger.info(
            "Daily failure materialization completed: %d records from %d tracked jobs",
            new_count,
            len(tracked_jobs),
        )
        return new_count

    @staticmethod
    def _match_snapshot(
        snapshot_map: dict[tuple[str, str, str, str], NightlyTestCase],
        fallback_snapshots: dict[tuple[str, str], list[NightlyTestCase]],
        *,
        report_date: str,
        source_branch: str,
        workflow_name: str,
        job_name: str,
    ) -> NightlyTestCase | None:
        """Match a failed job to an exact or historical YAML snapshot."""

        for (snapshot_date, branch, workflow, snapshot_job), value in snapshot_map.items():
            if snapshot_date != report_date or branch != source_branch or workflow != workflow_name:
                continue
            if (value.test_model and value.test_model in job_name) or snapshot_job in job_name:
                return value

        for candidate in fallback_snapshots.get((source_branch, workflow_name), []):
            if (candidate.test_model and candidate.test_model in job_name) or candidate.job_name in job_name:
                return candidate
        return None
