import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PullRequest
from app.services.github_client import GitHubRateLimitError
from app.services.pr_pipeline_collector import PRPipelineCollector

logger = logging.getLogger(__name__)


class PRPipelineHistoricalCollector(PRPipelineCollector):

    async def collect_phase_a(self, owner: str, repo: str) -> int:
        logger.info(f"Phase A: Collecting all open PRs for {owner}/{repo}")

        stmt = select(sa_func.count(PullRequest.id)).where(
            PullRequest.owner == owner,
            PullRequest.repo == repo,
            PullRequest.state == "open",
        )
        result = await self.db.execute(stmt)
        existing_open = result.scalar() or 0

        since = datetime.now(UTC) - timedelta(days=365)
        count = await self.collect_prs(owner, repo, since=since, days_back=365)

        logger.info(f"Phase A complete: collected {count} PRs (had {existing_open} existing open)")
        return count

    async def collect_phase_b(self, owner: str, repo: str, months_back: int = 3) -> int:
        logger.info(f"Phase B: Collecting recent merged/closed PRs for {owner}/{repo} (last {months_back} months)")

        since = datetime.now(UTC) - timedelta(days=months_back * 30)
        count = await self.collect_prs(owner, repo, since=since, days_back=months_back * 30)

        logger.info(f"Phase B complete: collected {count} PRs")
        return count

    async def collect_phase_c(self, owner: str, repo: str, months_back: int = 12) -> int:
        logger.info(f"Phase C: Full historical collection for {owner}/{repo} (last {months_back} months)")

        total_count = 0
        batch_size_days = 30

        for month_offset in range(months_back):
            start = datetime.now(UTC) - timedelta(days=(month_offset + 1) * batch_size_days)
            end = datetime.now(UTC) - timedelta(days=month_offset * batch_size_days)

            await self._check_rate_limit_and_wait()

            stmt = select(sa_func.count(PullRequest.id)).where(
                PullRequest.owner == owner,
                PullRequest.repo == repo,
                PullRequest.created_at >= start,
                PullRequest.created_at < end,
            )
            result = await self.db.execute(stmt)
            existing_in_batch = result.scalar() or 0

            if existing_in_batch > 0:
                logger.info(f"Month {month_offset + 1}: already have {existing_in_batch} PRs, checking for gaps")

            try:
                count = await self.collect_prs(owner, repo, since=start, days_back=batch_size_days)
                total_count += count
                logger.info(f"Month {month_offset + 1}/{months_back}: collected {count} PRs")
            except GitHubRateLimitError as e:
                logger.warning(f"Rate limit hit in Phase C month {month_offset + 1}: {e}")
                await asyncio.sleep(60)
                continue

            await asyncio.sleep(2)

        logger.info(f"Phase C complete: collected {total_count} PRs across {months_back} months")
        return total_count

    async def collect_historical(
        self,
        owner: str,
        repo: str,
        phases: list[str] = ["A", "B"],
        months_back: int = 3,
    ) -> dict[str, int]:
        results = {}

        if "A" in phases:
            results["phase_a"] = await self.collect_phase_a(owner, repo)

        if "B" in phases:
            results["phase_b"] = await self.collect_phase_b(owner, repo, months_back)

        if "C" in phases:
            results["phase_c"] = await self.collect_phase_c(owner, repo, months_back)

        logger.info(f"Historical collection complete: {results}")
        return results

    async def _check_rate_limit_and_wait(self):
        try:
            status = await self.github.get_rate_limit_status()
            core = status.get("core", {})
            remaining = core.get("remaining", 5000)

            if remaining < 500:
                reset_ts = core.get("reset")
                if reset_ts:
                    wait_time = max(0, reset_ts - int(datetime.now(UTC).timestamp()))
                    logger.info(f"Rate limit low ({remaining} remaining), waiting {wait_time}s")
                    await asyncio.sleep(min(wait_time + 10, 3600))
                else:
                    logger.info(f"Rate limit low ({remaining} remaining), waiting 60s")
                    await asyncio.sleep(60)
        except Exception as e:
            logger.warning(f"Failed to check rate limit: {e}")
