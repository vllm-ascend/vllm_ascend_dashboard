import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Unicode

from app.models import PullRequest
from app.schemas.pr_pipeline import (
    PRPipelineContributor,
    PRPipelineKanban,
    PRPipelineListResponse,
    PRPipelineMetrics,
    PRPipelineOverview,
    PRPipelinePercentileMetric,
    PRPipelineStageDistribution,
    PRPipelineTrendPoint,
    PRPipelineTrendsResponse,
    PullRequestResponse,
)

logger = logging.getLogger(__name__)


class PRPipelineService:

    async def get_overview(
        self,
        db: AsyncSession,
        owner: str,
        repo: str,
        days: int = 30,
    ) -> PRPipelineOverview:
        now = datetime.now(UTC)
        since = now - timedelta(days=days)

        open_count = await self._count_by_state(db, owner, repo, "open")
        merged_count = await self._count_by_state(db, owner, repo, "merged")
        closed_count = await self._count_by_state(db, owner, repo, "closed")
        draft_count = await self._count_by_state(db, owner, repo, "open", is_draft=True)

        stmt = select(PullRequest.pipeline_stage, func.count(PullRequest.id)).where(
            PullRequest.owner == owner,
            PullRequest.repo == repo,
            PullRequest.state == "open",
        ).group_by(PullRequest.pipeline_stage)
        result = await db.execute(stmt)
        stage_counts = {row[0] or "submitted": row[1] for row in result.all()}

        distribution = PRPipelineStageDistribution(
            submitted=stage_counts.get("submitted", 0),
            reviewing=stage_counts.get("reviewing", 0),
            approved=stage_counts.get("approved", 0),
            ci_running=stage_counts.get("ci_running", 0),
            ci_passed=stage_counts.get("ci_passed", 0),
            ci_failed=stage_counts.get("ci_failed", 0),
            merging=stage_counts.get("merging", 0),
            merged=merged_count,
            closed=closed_count,
        )

        recent_opened = await self._count_since(db, owner, repo, "open", since)
        recent_merged = await self._count_since(db, owner, repo, "merged", since)

        open_non_draft = open_count - draft_count
        daily_merge_avg = recent_merged / days if days > 0 else 0.0
        if daily_merge_avg > 0:
            backlog_index = round(open_non_draft / daily_merge_avg, 1)
        else:
            backlog_index = round(float(open_non_draft), 1) if open_non_draft > 0 else 0.0
        backlog_level = "green" if backlog_index < 1.5 else ("yellow" if backlog_index < 3 else "red")
        merge_rate = round(merged_count / max(merged_count + closed_count, 1), 2)

        avg_first_review = await self._avg_hours(db, owner, repo, "first_review_at", "created_at", days)
        avg_merge = await self._avg_hours(db, owner, repo, "merged_at", "created_at", days)

        stmt = select(PullRequest.updated_at).where(
            PullRequest.owner == owner,
            PullRequest.repo == repo,
        ).order_by(desc(PullRequest.updated_at)).limit(1)
        result = await db.execute(stmt)
        last_sync_row = result.scalar_one_or_none()

        return PRPipelineOverview(
            open_count=open_count,
            merged_count=merged_count,
            closed_count=closed_count,
            draft_count=draft_count,
            backlog_index=backlog_index,
            backlog_level=backlog_level,
            merge_rate=merge_rate,
            avg_time_to_first_review_hours=avg_first_review,
            avg_time_to_merge_hours=avg_merge,
            pipeline_stage_distribution=distribution,
            recent_opened_count=recent_opened,
            recent_merged_count=recent_merged,
            last_sync_at=last_sync_row,
        )

    async def get_kanban(
        self,
        db: AsyncSession,
        owner: str,
        repo: str,
        state: str | None = "open",
        include_draft: bool = False,
        limit_per_stage: int = 20,
    ) -> PRPipelineKanban:
        conditions = [
            PullRequest.owner == owner,
            PullRequest.repo == repo,
        ]
        if state:
            conditions.append(PullRequest.state == state)
        if not include_draft:
            conditions.append(PullRequest.is_draft == False)

        stmt = select(PullRequest).where(*conditions).order_by(PullRequest.updated_at.desc())
        result = await db.execute(stmt)
        all_prs = result.scalars().all()

        stages: dict[str, list[PullRequestResponse]] = {
            "submitted": [], "reviewing": [], "approved": [],
            "ci_running": [], "ci_passed": [], "ci_failed": [],
            "merging": [], "merged": [], "closed": [],
        }

        for pr in all_prs:
            stage = pr.pipeline_stage or "submitted"
            resp = PullRequestResponse.model_validate(pr)
            if len(stages.get(stage, [])) < limit_per_stage:
                stages.setdefault(stage, []).append(resp)

        return PRPipelineKanban(**stages)

    async def get_list(
        self,
        db: AsyncSession,
        owner: str,
        repo: str,
        state: str | None = None,
        author: str | None = None,
        pipeline_stage: str | None = None,
        review_status: str | None = None,
        ci_status: str | None = None,
        is_draft: bool | None = None,
        base_branch: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        label: str | None = None,
        search: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        page: int = 1,
        page_size: int = 20,
    ) -> PRPipelineListResponse:
        conditions = [
            PullRequest.owner == owner,
            PullRequest.repo == repo,
        ]
        if state:
            conditions.append(PullRequest.state == state)
        if author:
            conditions.append(PullRequest.author == author)
        if pipeline_stage:
            conditions.append(PullRequest.pipeline_stage == pipeline_stage)
        if review_status:
            conditions.append(PullRequest.review_status == review_status)
        if ci_status:
            conditions.append(PullRequest.ci_status == ci_status)
        if is_draft is not None:
            conditions.append(PullRequest.is_draft == is_draft)
        if base_branch:
            conditions.append(PullRequest.base_branch == base_branch)
        if label:
            conditions.append(PullRequest.labels.cast(Unicode).like(f"%{label}%"))
        if search:
            conditions.append(PullRequest.title.ilike(f"%{search}%"))
        if date_from:
            try:
                df = datetime.fromisoformat(date_from).replace(tzinfo=UTC)
                conditions.append(PullRequest.created_at >= df)
            except ValueError:
                pass
        if date_to:
            try:
                dt = datetime.fromisoformat(date_to).replace(tzinfo=UTC)
                conditions.append(PullRequest.created_at <= dt)
            except ValueError:
                pass

        count_stmt = select(func.count(PullRequest.id)).where(*conditions)
        total_result = await db.execute(count_stmt)
        total = total_result.scalar() or 0

        sort_col = getattr(PullRequest, sort_by, PullRequest.updated_at)
        if sort_order == "desc":
            sort_col = desc(sort_col)

        stmt = select(PullRequest).where(*conditions).order_by(sort_col).offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(stmt)
        prs = result.scalars().all()

        items = [PullRequestResponse.model_validate(pr) for pr in prs]

        return PRPipelineListResponse(
            total=total,
            items=items,
            page=page,
            page_size=page_size,
        )

    async def get_metrics(
        self,
        db: AsyncSession,
        owner: str,
        repo: str,
        days: int = 30,
    ) -> PRPipelineMetrics:
        now = datetime.now(UTC)
        since = now - timedelta(days=days)

        conditions = [
            PullRequest.owner == owner,
            PullRequest.repo == repo,
            PullRequest.created_at >= since,
        ]

        first_response = await self._percentile(db, conditions, "first_review_at", "created_at")
        review_to_approval = await self._percentile(db, conditions, "first_approved_at", "first_review_at")
        ci_duration = await self._percentile(db, conditions, "ci_completed_at", "ci_started_at")
        merge_hours = await self._percentile(db, conditions, "merged_at", "created_at")
        total_cycle = await self._percentile(db, conditions, "merged_at", "created_at", require_state="merged")

        merged_count = await self._count_by_state(db, owner, repo, "merged")
        closed_count = await self._count_by_state(db, owner, repo, "closed")
        open_count = await self._count_by_state(db, owner, repo, "open")
        draft_count = await self._count_by_state(db, owner, repo, "open", is_draft=True)

        merge_rate = round(merged_count / max(merged_count + closed_count, 1), 2)
        recent_merged = await self._count_since(db, owner, repo, "merged", since)
        open_non_draft = open_count - draft_count
        daily_merge_avg = recent_merged / days if days > 0 else 0.0
        if daily_merge_avg > 0:
            backlog_index = round(open_non_draft / daily_merge_avg, 1)
        else:
            backlog_index = round(float(open_non_draft), 1) if open_non_draft > 0 else 0.0

        survival = await self._survival_distribution(db, owner, repo, days)
        slowest = await self._slowest_prs(db, owner, repo, since)

        return PRPipelineMetrics(
            first_response_hours=first_response,
            review_to_approval_hours=review_to_approval,
            ci_duration_hours=ci_duration,
            merge_hours=merge_hours,
            total_cycle_hours=total_cycle,
            merge_rate=merge_rate,
            backlog_index=backlog_index,
            survival_distribution=survival,
            slowest_prs=slowest,
        )

    async def get_contributors(
        self,
        db: AsyncSession,
        owner: str,
        repo: str,
        days: int = 30,
        type: str | None = None,
        limit: int = 20,
    ) -> list[PRPipelineContributor]:
        now = datetime.now(UTC)
        since = now - timedelta(days=days)

        contributors: list[PRPipelineContributor] = []

        if type is None or type == "author":
            stmt = select(
                PullRequest.author,
                PullRequest.author_avatar_url,
                func.count(PullRequest.id).label("pr_count"),
                func.sum(PullRequest.additions).label("lines_added"),
                func.sum(PullRequest.deletions).label("lines_removed"),
            ).where(
                PullRequest.owner == owner,
                PullRequest.repo == repo,
                PullRequest.created_at >= since,
            ).group_by(PullRequest.author, PullRequest.author_avatar_url).order_by(desc("pr_count")).limit(limit)
            result = await db.execute(stmt)
            for row in result.all():
                merged_stmt = select(func.count(PullRequest.id)).where(
                    PullRequest.owner == owner,
                    PullRequest.repo == repo,
                    PullRequest.author == row[0],
                    PullRequest.state == "merged",
                    PullRequest.created_at >= since,
                )
                merged_result = await db.execute(merged_stmt)
                merged_count = merged_result.scalar() or 0

                contributors.append(PRPipelineContributor(
                    username=row[0],
                    avatar_url=row[1],
                    type="author",
                    pr_count=row[2],
                    lines_added=row[3] or 0,
                    lines_removed=row[4] or 0,
                    merged_count=merged_count,
                ))

        if type is None or type == "reviewer":
            stmt = select(PullRequest.reviewers, PullRequest.first_review_at, PullRequest.created_at).where(
                PullRequest.owner == owner,
                PullRequest.repo == repo,
                PullRequest.first_review_at.isnot(None),
                PullRequest.created_at >= since,
            )
            result = await db.execute(stmt)
            reviewer_stats: dict[str, dict[str, Any]] = {}
            for row in result.all():
                reviewers_data = row[0] or []
                for r in reviewers_data:
                    login = r.get("login", "")
                    if not login:
                        continue
                    if login not in reviewer_stats:
                        reviewer_stats[login] = {"count": 0, "response_hours": []}
                    reviewer_stats[login]["count"] += 1
                    if row[1] and row[2]:
                        hours = (row[1] - row[2]).total_seconds() / 3600
                        reviewer_stats[login]["response_hours"].append(hours)

            sorted_reviewers = sorted(reviewer_stats.items(), key=lambda x: x[1]["count"], reverse=True)[:limit]
            for login, stats in sorted_reviewers:
                avg_response = None
                if stats["response_hours"]:
                    avg_response = round(sum(stats["response_hours"]) / len(stats["response_hours"]), 1)

                contributors.append(PRPipelineContributor(
                    username=login,
                    type="reviewer",
                    review_count=stats["count"],
                    avg_first_response_hours=avg_response,
                ))

        return contributors

    async def get_trends(
        self,
        db: AsyncSession,
        owner: str,
        repo: str,
        days: int = 30,
    ) -> PRPipelineTrendsResponse:
        now = datetime.now(UTC)
        since = now - timedelta(days=days)

        trends: list[PRPipelineTrendPoint] = []
        for i in range(days):
            day = since + timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            opened = await self._count_in_range(db, owner, repo, "created_at", day_start, day_end)
            merged = await self._count_in_range(db, owner, repo, "merged_at", day_start, day_end, state="merged")
            closed = await self._count_in_range(db, owner, repo, "closed_at", day_start, day_end)

            open_total = await self._count_open_on_date(db, owner, repo, day_end)

            trends.append(PRPipelineTrendPoint(
                date=day_start.strftime("%Y-%m-%d"),
                opened=opened,
                merged=merged,
                closed=closed,
                open_total=open_total,
            ))

        return PRPipelineTrendsResponse(trends=trends, period_days=days)

    async def get_pr_detail(
        self,
        db: AsyncSession,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> PullRequestResponse | None:
        stmt = select(PullRequest).where(
            PullRequest.pr_number == pr_number,
            PullRequest.owner == owner,
            PullRequest.repo == repo,
        )
        result = await db.execute(stmt)
        pr = result.scalar_one_or_none()
        if not pr:
            return None
        return PullRequestResponse.model_validate(pr)

    async def _count_by_state(
        self,
        db: AsyncSession,
        owner: str,
        repo: str,
        state: str,
        is_draft: bool | None = None,
    ) -> int:
        conditions = [
            PullRequest.owner == owner,
            PullRequest.repo == repo,
            PullRequest.state == state,
        ]
        if is_draft is not None:
            conditions.append(PullRequest.is_draft == is_draft)
        stmt = select(func.count(PullRequest.id)).where(*conditions)
        result = await db.execute(stmt)
        return result.scalar() or 0

    async def _count_since(
        self,
        db: AsyncSession,
        owner: str,
        repo: str,
        state: str,
        since: datetime,
    ) -> int:
        conditions = [
            PullRequest.owner == owner,
            PullRequest.repo == repo,
            PullRequest.state == state,
        ]
        if state == "merged":
            conditions.append(PullRequest.merged_at >= since)
        elif state == "open":
            conditions.append(PullRequest.created_at >= since)
        else:
            conditions.append(PullRequest.closed_at >= since)

        stmt = select(func.count(PullRequest.id)).where(*conditions)
        result = await db.execute(stmt)
        return result.scalar() or 0

    async def _avg_hours(
        self,
        db: AsyncSession,
        owner: str,
        repo: str,
        end_col: str,
        start_col: str,
        days: int,
    ) -> float | None:
        since = datetime.now(UTC) - timedelta(days=days)
        stmt = select(
            PullRequest.id,
            getattr(PullRequest, end_col),
            getattr(PullRequest, start_col),
        ).where(
            PullRequest.owner == owner,
            PullRequest.repo == repo,
            getattr(PullRequest, end_col).isnot(None),
            getattr(PullRequest, start_col).isnot(None),
            PullRequest.created_at >= since,
        )
        result = await db.execute(stmt)
        rows = result.all()
        if not rows:
            return None
        hours_list = [
            (row[1] - row[2]).total_seconds() / 3600
            for row in rows
            if row[1] is not None and row[2] is not None
        ]
        if not hours_list:
            return None
        return round(sum(hours_list) / len(hours_list), 1)

    async def _percentile(
        self,
        db: AsyncSession,
        base_conditions: list,
        end_col: str,
        start_col: str,
        require_state: str | None = None,
    ) -> PRPipelinePercentileMetric:
        conditions = list(base_conditions)
        end_attr = getattr(PullRequest, end_col)
        start_attr = getattr(PullRequest, start_col)
        conditions.extend([end_attr.isnot(None), start_attr.isnot(None)])
        if require_state:
            conditions.append(PullRequest.state == require_state)

        stmt = select(
            PullRequest.id,
            end_attr,
            start_attr,
        ).where(*conditions)
        result = await db.execute(stmt)
        rows = result.all()

        values = [
            (row[1] - row[2]).total_seconds() / 3600
            for row in rows
            if row[1] is not None and row[2] is not None
        ]

        if not values:
            return PRPipelinePercentileMetric(p50=None, p90=None, avg=None, count=0)

        values.sort()
        n = len(values)
        avg = round(sum(values) / n, 1)
        p50 = round(values[int(n * 0.5)], 1) if n > 0 else None
        p90 = round(values[int(n * 0.9)], 1) if n > 1 else round(values[-1], 1) if n > 0 else None

        return PRPipelinePercentileMetric(p50=p50, p90=p90, avg=avg, count=n)

    async def _slowest_prs(
        self,
        db: AsyncSession,
        owner: str,
        repo: str,
        since: datetime,
        limit: int = 10,
    ) -> list[dict]:
        """最慢合并的 PR（按 created_at → merged_at 耗时倒序）Top N。"""
        stmt = select(
            PullRequest.pr_number,
            PullRequest.title,
            PullRequest.author,
            PullRequest.author_avatar_url,
            PullRequest.html_url,
            PullRequest.merged_at,
            PullRequest.created_at,
        ).where(
            PullRequest.owner == owner,
            PullRequest.repo == repo,
            PullRequest.state == "merged",
            PullRequest.merged_at.isnot(None),
            PullRequest.created_at >= since,
        )
        result = await db.execute(stmt)
        rows = result.all()
        items: list[dict] = []
        for r in rows:
            if r[5] is None or r[6] is None:
                continue
            hours = round((r[5] - r[6]).total_seconds() / 3600, 1)
            items.append({
                "pr_number": r[0],
                "title": r[1],
                "author": r[2],
                "author_avatar_url": r[3],
                "html_url": r[4],
                "hours": hours,
            })
        items.sort(key=lambda x: x["hours"], reverse=True)
        return items[:limit]

    async def _survival_distribution(
        self,
        db: AsyncSession,
        owner: str,
        repo: str,
        days: int,
    ) -> list[dict[str, Any]]:
        since = datetime.now(UTC) - timedelta(days=days)
        stmt = select(PullRequest).where(
            PullRequest.owner == owner,
            PullRequest.repo == repo,
            PullRequest.merged_at.isnot(None),
            PullRequest.created_at >= since,
        )
        result = await db.execute(stmt)
        merged_prs = result.scalars().all()

        if not merged_prs:
            return []

        hours_list = []
        for pr in merged_prs:
            if pr.merged_at and pr.created_at:
                hours_list.append((pr.merged_at - pr.created_at).total_seconds() / 3600)

        if not hours_list:
            return []

        hours_list.sort()
        n = len(hours_list)

        distribution = []
        for day in range(0, 31):
            threshold_hours = day * 24
            count_merged_by_day = sum(1 for h in hours_list if h <= threshold_hours)
            cumulative_percent = round(count_merged_by_day / n * 100, 1)
            distribution.append({
                "day": day,
                "hours_threshold": threshold_hours,
                "cumulative_percent": cumulative_percent,
                "count": count_merged_by_day,
            })

        return distribution

    async def _count_in_range(
        self,
        db: AsyncSession,
        owner: str,
        repo: str,
        col: str,
        start: datetime,
        end: datetime,
        state: str | None = None,
    ) -> int:
        attr = getattr(PullRequest, col)
        conditions = [
            PullRequest.owner == owner,
            PullRequest.repo == repo,
            attr >= start,
            attr < end,
        ]
        if state:
            conditions.append(PullRequest.state == state)
        stmt = select(func.count(PullRequest.id)).where(*conditions)
        result = await db.execute(stmt)
        return result.scalar() or 0

    async def _count_open_on_date(
        self,
        db: AsyncSession,
        owner: str,
        repo: str,
        date: datetime,
    ) -> int:
        conditions = [
            PullRequest.owner == owner,
            PullRequest.repo == repo,
            PullRequest.state == "open",
            PullRequest.created_at < date,
        ]
        stmt = select(func.count(PullRequest.id)).where(*conditions)
        result = await db.execute(stmt)
        return result.scalar() or 0
