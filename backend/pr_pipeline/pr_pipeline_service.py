import json
import logging
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, desc, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.types import Unicode

from contracts.schemas.pr_pipeline import (
    PRPipelineContributor,
    PRPipelineContributorsResponse,
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
from infrastructure.persistence.models import CIJob, CIResult, PullRequest, ResourceNpuMetrics
from tooling.company_detector import detect_company

logger = logging.getLogger(__name__)

ACTIVE_CI_JOB_STATUSES = {"queued", "in_progress", "pending", "waiting", "requested"}
PR_CI_EVENTS = {"pull_request", "pull_request_target", "push"}
NPU_CARD_PATTERNS = (
    re.compile(r"\b(\d+)\s*cards?\b", re.IGNORECASE),
    # Match runner labels such as ``linux-aarch64-a3-4``.  The lookahead is
    # intentional: ``a3-560t`` is a hardware/cluster name, not 560 cards.
    re.compile(
        r"(?:^|[-_ ])(?:a2b3|a2|a3|310p|npu-static)[-_ ](\d+)(?=$|[-_ ])",
        re.IGNORECASE,
    ),
)


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
            conditions.append(not PullRequest.is_draft)

        stmt = select(PullRequest).where(*conditions).order_by(PullRequest.updated_at.desc())
        result = await db.execute(stmt)
        all_prs = result.scalars().all()
        npu_stats = await self._get_npu_stats(db, all_prs)

        stages: dict[str, list[PullRequestResponse]] = {
            "submitted": [], "reviewing": [], "approved": [],
            "ci_running": [], "ci_passed": [], "ci_failed": [],
            "merging": [], "merged": [], "closed": [],
        }

        for pr in all_prs:
            stage = pr.pipeline_stage or "submitted"
            resp = self._pr_response_with_npu(pr, npu_stats)
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

        npu_stats = await self._get_npu_stats(db, prs)
        items = [self._pr_response_with_npu(pr, npu_stats) for pr in prs]

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
        skip: int = 0,
        limit: int = 20,
        company: str | None = None,
        sort_by: str = "pr_count",
    ) -> PRPipelineContributorsResponse:
        now = datetime.now(UTC)
        since = now - timedelta(days=days)

        # Map sort_by to actual column
        author_sort_map = {
            "pr_count": desc("pr_count"),
            "merged_count": desc("pr_count"),  # merged_count is a separate query, default to pr_count
            "lines_added": desc("lines_added"),
            "lines_removed": desc("lines_removed"),
        }
        order_clause = author_sort_map.get(sort_by, desc("pr_count"))

        contributors: list[PRPipelineContributor] = []
        author_total = 0
        reviewer_total = 0

        if type is None or type == "author":
            base_stmt = select(
                PullRequest.author,
                func.max(PullRequest.author_avatar_url).label("author_avatar_url"),
                func.max(PullRequest.author_avatar_base64).label("author_avatar_base64"),
                func.max(PullRequest.author_email).label("author_email"),
            ).where(
                PullRequest.owner == owner,
                PullRequest.repo == repo,
                PullRequest.created_at >= since,
            )

            # Company filter at SQL level
            if company == "华为":
                base_stmt = base_stmt.where(PullRequest.author_email.like("%@huawei.com"))
            elif company == "none":
                base_stmt = base_stmt.where(
                    (PullRequest.author_email.is_(None)) |
                    (PullRequest.author_email.not_like("%@huawei.com"))
                )

            base_stmt = base_stmt.group_by(PullRequest.author)

            # COUNT query for total (wrap GROUP BY in subquery to count groups)
            count_subq = base_stmt.with_only_columns(literal_column("1")).order_by(None).subquery()
            count_stmt = select(func.count()).select_from(count_subq)
            author_total = (await db.execute(count_stmt)).scalar() or 0

            # Data query with aggregates + sort + offset + limit
            data_stmt = base_stmt.add_columns(
                func.count(PullRequest.id).label("pr_count"),
                func.sum(case((PullRequest.state == "merged", 1), else_=0)).label("merged_count"),
                func.sum(PullRequest.additions).label("lines_added"),
                func.sum(PullRequest.deletions).label("lines_removed"),
            ).order_by(order_clause)

            if type == "author":
                data_stmt = data_stmt.offset(skip).limit(limit)
            else:
                data_stmt = data_stmt.limit(limit * 5)  # both types: reasonable cap

            result = await db.execute(data_stmt)
            author_rows = result.all()
            author_names = [row[0] for row in author_rows]
            fallback_emails = {row[0]: row[3] for row in author_rows}
            author_emails = await self._get_authors_emails(
                db,
                owner,
                repo,
                author_names,
                since,
                fallback_emails,
            )

            for row in author_rows:
                emails = author_emails.get(row[0], [])
                primary_email = emails[0] if emails else None
                contributors.append(PRPipelineContributor(
                    username=row[0],
                    avatar_url=row[1],
                    emails=emails,
                    primary_email=primary_email,
                    avatar_base64=row[2],
                    type="author",
                    company=detect_company(primary_email),
                    pr_count=row[4],
                    merged_count=row[5] or 0,
                    lines_added=row[6] or 0,
                    lines_removed=row[7] or 0,
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

            sorted_reviewers = sorted(reviewer_stats.items(), key=lambda x: x[1]["count"], reverse=True)

            # Batch-fetch emails for reviewer logins from PullRequest author data
            reviewer_emails: dict[str, str | None] = {}
            if sorted_reviewers:
                reviewer_logins = [login for login, _ in sorted_reviewers]
                email_stmt = select(
                    PullRequest.author,
                    PullRequest.author_email,
                ).where(
                    PullRequest.owner == owner,
                    PullRequest.repo == repo,
                    PullRequest.author.in_(reviewer_logins),
                    PullRequest.author_email.isnot(None),
                ).distinct()
                email_result = await db.execute(email_stmt)
                for row in email_result.all():
                    if row[0] and row[1]:
                        reviewer_emails[row[0]] = row[1]


            # Build sorted contributor list with company info
            sorted_contribs = []
            for login, stats in sorted_reviewers:
                avg_response = None
                if stats["response_hours"]:
                    avg_response = round(sum(stats["response_hours"]) / len(stats["response_hours"]), 1)
                sorted_contribs.append((login, stats, avg_response, detect_company(reviewer_emails.get(login))))

            # Company filter at Python level (reviewer company comes from DB/GitHub lookup)
            if company == "华为":
                sorted_contribs = [(username, stats, avg, company) for username, stats, avg, company in sorted_contribs if company == "华为"]
            elif company == "none":
                sorted_contribs = [(username, stats, avg, company) for username, stats, avg, company in sorted_contribs if company is None]

            # Sort reviewers
            if sort_by == "avg_first_response_hours":
                sorted_contribs.sort(key=lambda x: x[2] or float("inf"))
            else:
                sorted_contribs.sort(key=lambda x: x[1]["count"], reverse=True)

            for login, stats, avg_response, contrib_company in sorted_contribs:
                contributors.append(PRPipelineContributor(
                    username=login,
                    type="reviewer",
                    company=contrib_company,
                    review_count=stats["count"],
                    avg_first_response_hours=avg_response,
                ))

            reviewer_total = len(sorted_contribs)  # count after company filter, before pagination

            # Apply pagination for reviewer-only requests (authors already added above)
            if type == "reviewer":
                # Keep only reviewers, apply skip/limit
                reviewers_only = [c for c in contributors if c.type == "reviewer"]
                contributors = [c for c in contributors if c.type == "author"] + reviewers_only[skip:skip + limit]

        if type is None:
            # Both types: cap each list independently
            author_items = [c for c in contributors if c.type == "author"][:limit]
            reviewer_items = [c for c in contributors if c.type == "reviewer"][:limit]
            contributors = author_items + reviewer_items

        return PRPipelineContributorsResponse(
            total=author_total + reviewer_total,
            items=contributors,
        )

    async def _get_authors_emails(
        self,
        db: AsyncSession,
        owner: str,
        repo: str,
        authors: list[str],
        since: datetime,
        fallback_emails: dict[str, str | None],
    ) -> dict[str, list[str]]:
        if not authors:
            return {}

        stmt = select(PullRequest.author, PullRequest.data).where(
            PullRequest.owner == owner,
            PullRequest.repo == repo,
            PullRequest.author.in_(authors),
            PullRequest.created_at >= since,
        )
        result = await db.execute(stmt)
        counts_by_author = {author: Counter() for author in authors}

        for author, fallback_email in fallback_emails.items():
            if fallback_email:
                counts_by_author[author][fallback_email] += 1

        for author, data in result.all():
            commits = (data or {}).get("commits") or []
            if not isinstance(commits, list):
                continue
            for commit in commits:
                if not isinstance(commit, dict):
                    continue
                commit_author = commit.get("author") or {}
                login = commit_author.get("login") if isinstance(commit_author, dict) else None
                if login and login != author:
                    continue

                commit_data = commit.get("commit") or {}
                author_data = commit_data.get("author") if isinstance(commit_data, dict) else {}
                email = author_data.get("email") if isinstance(author_data, dict) else None
                if email:
                    counts_by_author[author][email] += 1

        return {
            author: [email for email, _ in counts.most_common()]
            for author, counts in counts_by_author.items()
        }

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
        npu_stats = await self._get_npu_stats(db, [pr])
        return self._pr_response_with_npu(pr, npu_stats)

    @staticmethod
    def _npu_cards_for_job(job: CIJob) -> float:
        """Extract the requested NPU count from CI job metadata."""
        candidates: list[str] = []
        raw_labels = job.runner_labels
        if raw_labels:
            try:
                labels = json.loads(raw_labels) if isinstance(raw_labels, str) else raw_labels
                if isinstance(labels, list):
                    candidates.extend(str(label) for label in labels)
            except (TypeError, ValueError):
                candidates.append(str(raw_labels))
        candidates.extend(filter(None, [job.job_name, job.runner_name]))

        for candidate in candidates:
            for pattern in NPU_CARD_PATTERNS:
                match = pattern.search(candidate)
                if match:
                    return float(match.group(1))
        return 0.0

    @staticmethod
    def _job_has_pending_npu(job: CIJob) -> bool:
        """Return whether a CI job can still hold or request NPU capacity."""
        conclusion = str(job.conclusion or "").strip().lower()
        if conclusion:
            return False
        status = str(job.status or "").strip().lower()
        return status in ACTIVE_CI_JOB_STATUSES or status in {"", "unknown", "completed"}

    async def _get_npu_stats(
        self,
        db: AsyncSession,
        prs: list[PullRequest],
    ) -> dict[int, dict[str, float | int]]:
        """Return planned, allocated and still-needed NPU cards per PR.

        The latest associated workflow run is the unit of accounting. Only
        unfinished NPU jobs are planned demand; currently running PR pods are
        subtracted from that demand.
        """
        stats = {
            int(pr.pr_number): {
                "planned_npu": 0.0,
                "allocated_npu": 0.0,
                "npu_demand": 0.0,
                "pending_npu_jobs": 0,
            }
            for pr in prs
        }
        if not stats:
            return stats

        sha_to_pr_numbers: dict[str, list[int]] = defaultdict(list)
        explicit_run_by_pr: dict[int, int] = {}
        for pr in prs:
            if pr.head_sha:
                sha_to_pr_numbers[pr.head_sha].append(int(pr.pr_number))
            if pr.ci_workflow_run_id:
                explicit_run_by_pr[int(pr.pr_number)] = int(pr.ci_workflow_run_id)

        run_to_pr_numbers: dict[int, list[int]] = defaultdict(list)
        if sha_to_pr_numbers:
            run_rows = (
                await db.execute(
                    select(CIResult)
                    .where(CIResult.head_sha.in_(list(sha_to_pr_numbers)))
                    .order_by(desc(CIResult.created_at), desc(CIResult.started_at))
                )
            ).scalars().all()
            runs_by_sha: dict[str, list[CIResult]] = defaultdict(list)
            for run in run_rows:
                if run.head_sha:
                    runs_by_sha[run.head_sha].append(run)

            for pr in prs:
                pr_number = int(pr.pr_number)
                if not pr.head_sha:
                    continue
                run_id = explicit_run_by_pr.get(pr_number)
                if run_id is None:
                    candidates = runs_by_sha.get(pr.head_sha, [])
                    preferred = [run for run in candidates if run.event in PR_CI_EVENTS]
                    selected = preferred or candidates
                    run_id = selected[0].run_id if selected else None
                if run_id is not None:
                    run_to_pr_numbers[int(run_id)].append(pr_number)

        mapped_pr_numbers = {
            pr_number
            for values in run_to_pr_numbers.values()
            for pr_number in values
        }
        for pr_number, run_id in explicit_run_by_pr.items():
            if pr_number in stats and pr_number not in mapped_pr_numbers:
                run_to_pr_numbers[run_id].append(pr_number)

        if run_to_pr_numbers:
            job_rows = (
                await db.execute(
                    select(CIJob).where(CIJob.run_id.in_(list(run_to_pr_numbers)))
                )
            ).scalars().all()
            for job in job_rows:
                cards = self._npu_cards_for_job(job)
                if cards <= 0 or not self._job_has_pending_npu(job):
                    continue
                for pr_number in run_to_pr_numbers.get(int(job.run_id), []):
                    stats[pr_number]["planned_npu"] += cards
                    stats[pr_number]["pending_npu_jobs"] += 1

        latest_metrics = (
            select(
                ResourceNpuMetrics.cluster_id,
                func.max(ResourceNpuMetrics.collected_at).label("latest_at"),
            )
            .group_by(ResourceNpuMetrics.cluster_id)
            .subquery()
        )
        metric_rows = (
            await db.execute(
                select(ResourceNpuMetrics).join(
                    latest_metrics,
                    and_(
                        ResourceNpuMetrics.cluster_id == latest_metrics.c.cluster_id,
                        ResourceNpuMetrics.collected_at == latest_metrics.c.latest_at,
                    ),
                )
            )
        ).scalars().all()

        seen_pods: set[tuple[int, str, str]] = set()
        for metric in metric_rows:
            pods = metric.top_pods_json or []
            if isinstance(pods, str):
                try:
                    pods = json.loads(pods)
                except (TypeError, ValueError):
                    pods = []
            for pod in pods if isinstance(pods, list) else []:
                if not isinstance(pod, dict) or pod.get("phase") != "Running":
                    continue
                try:
                    pr_number = int(pod.get("pr_number"))
                except (TypeError, ValueError):
                    continue
                if pr_number not in stats:
                    continue
                pod_key = (
                    int(metric.cluster_id),
                    str(pod.get("namespace") or ""),
                    str(pod.get("name") or ""),
                )
                if pod_key in seen_pods:
                    continue
                seen_pods.add(pod_key)
                try:
                    stats[pr_number]["allocated_npu"] += float(pod.get("npu") or 0)
                except (TypeError, ValueError):
                    continue

        for values in stats.values():
            values["planned_npu"] = round(values["planned_npu"], 2)
            values["allocated_npu"] = round(values["allocated_npu"], 2)
            values["pending_npu_jobs"] = int(values["pending_npu_jobs"])
            values["npu_demand"] = round(
                max(values["planned_npu"] - values["allocated_npu"], 0),
                2,
            )
        return stats

    @staticmethod
    def _pr_response_with_npu(
        pr: PullRequest,
        npu_stats: dict[int, dict[str, float | int]],
    ) -> PullRequestResponse:
        response = PullRequestResponse.model_validate(pr)
        return response.model_copy(update=npu_stats.get(int(pr.pr_number), {}))

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
