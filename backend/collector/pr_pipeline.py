import base64
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.clients.github_client import GitHubAPIError, GitHubClient, GitHubRateLimitError
from infrastructure.persistence.models import CIResult, ProjectDashboardConfig, PullRequest

logger = logging.getLogger(__name__)

# MySQL TEXT stores at most 65,535 bytes.  Base64 is ASCII, but the data URI
# prefix and future schema changes need headroom; oversized avatars fall back
# to ``author_avatar_url`` so one large image cannot roll back the whole PR
# batch.
MAX_AVATAR_BASE64_LENGTH = 60_000
PR_BATCH_COMMIT_SIZE = 25
PR_SYNC_STATE_KEY = "pr_pipeline_sync_state"


class PRPipelineCollector:

    def __init__(self, github_client: GitHubClient, db_session: AsyncSession):
        self.github = github_client
        self.db = db_session

    async def collect_prs(
        self,
        owner: str,
        repo: str,
        since: datetime | None = None,
        days_back: int = 7,
        incremental: bool = False,
        max_items: int | None = None,
        lookback_minutes: int = 15,
    ) -> int:
        now = datetime.now(UTC)
        state_doc: dict[str, Any] | None = None
        state_key = f"{owner}/{repo}"
        if incremental:
            state_doc = await self._load_sync_state()
            state = state_doc.get(state_key, {}) if state_doc else {}
            watermark = self._parse_datetime(state.get("source_updated_at"))
            previous_batch_limited = bool(state.get("last_sync_limited"))
            if watermark:
                if previous_batch_limited:
                    # Continue a capped backlog from the oldest processed
                    # item.  The API cursor is exclusive, so the same page is
                    # not returned on every 30-minute run.
                    since = now - timedelta(days=days_back)
                else:
                    since = watermark - timedelta(minutes=max(0, lookback_minutes))
                logger.info(
                    "Incremental PR sync for %s/%s from watermark %s (lookback=%dm)",
                    owner,
                    repo,
                    watermark.isoformat(),
                    lookback_minutes,
                )
            elif since is None:
                since = now - timedelta(days=days_back)
                logger.info(
                    "Initial incremental PR sync for %s/%s: %d-day backfill",
                    owner,
                    repo,
                    days_back,
                )
            prs = await self.github.get_pull_requests_by_updated_range(
                owner,
                repo,
                since,
                now,
                max_items=max_items,
                resume_before=watermark if previous_batch_limited else None,
            )
        else:
            if since is None:
                since = now - timedelta(days=days_back)
            prs = await self.github.get_pull_requests_by_date_range(owner, repo, since, now)

        logger.info(
            "Fetched %d PRs for %s/%s since %s (incremental=%s, max_items=%s)",
            len(prs),
            owner,
            repo,
            since.isoformat(),
            incremental,
            max_items,
        )

        count = 0
        processed_source_times: list[datetime] = []
        processing_failed = False
        failed_source_cursors: list[tuple[datetime, int]] = []
        for pr in prs:
            try:
                pr_number = pr["number"]
                reviews = await self.github.get_pr_reviews(owner, repo, pr_number)
                files = await self.github.get_pr_files(owner, repo, pr_number)

                if "additions" not in pr or pr.get("additions") is None:
                    commit_items = pr.get("commits") if isinstance(pr.get("commits"), list) else []
                    try:
                        detail = await self.github.get_pr_detail(owner, repo, pr_number)
                        pr = {**pr, **detail}
                        if commit_items:
                            pr["commits"] = commit_items
                    except Exception as e:
                        logger.warning(f"Failed to fetch PR detail for #{pr_number}: {e}")

                if not isinstance(pr.get("commits"), list):
                    try:
                        pr["commits"] = await self.github.get_pr_commits(owner, repo, pr_number)
                    except Exception as e:
                        logger.warning(f"Failed to fetch PR commits for #{pr_number}: {e}")
                        pr["commits"] = []

                db_pr = await self._upsert_pr(pr, owner, repo, reviews, files)
                if db_pr:
                    count += 1
                    source_time = self._source_updated_at(pr)
                    if source_time:
                        processed_source_times.append(source_time)
                    if count % PR_BATCH_COMMIT_SIZE == 0:
                        await self.db.commit()
                        logger.info(
                            "Committed PR sync batch: %d PRs for %s/%s",
                            count,
                            owner,
                            repo,
                        )
            except GitHubRateLimitError as e:
                logger.error(f"Rate limit exceeded while processing PRs: {e}")
                processing_failed = True
                source_time = self._source_updated_at(pr)
                if source_time and isinstance(pr.get("number"), int):
                    failed_source_cursors.append((source_time, pr["number"]))
                break
            except GitHubAPIError as e:
                logger.error(f"API error processing PR #{pr.get('number', '?')}: {e}")
                processing_failed = True
                source_time = self._source_updated_at(pr)
                if source_time and isinstance(pr.get("number"), int):
                    failed_source_cursors.append((source_time, pr["number"]))
                continue
            except Exception as e:
                logger.error(f"Unexpected error processing PR #{pr.get('number', '?')}: {e}", exc_info=True)
                processing_failed = True
                source_time = self._source_updated_at(pr)
                if source_time and isinstance(pr.get("number"), int):
                    failed_source_cursors.append((source_time, pr["number"]))
                continue

        try:
            if incremental and state_doc is not None:
                # Advance only after all candidates have been attempted.  A
                # failed PR gets an inclusive continuation cursor so the next
                # run retries it instead of skipping it permanently.  When a
                # max_items cap truncated the page, the oldest successful
                # candidate becomes the next watermark and the following run
                # continues from there.
                if failed_source_cursors:
                    # Continue at the newest failed cursor.  The API resumes
                    # inclusively for the same timestamp, so all failed PRs
                    # at that timestamp are retried before older backlog data.
                    next_watermark = max(source_time for source_time, _ in failed_source_cursors)
                elif processed_source_times:
                    next_watermark = min(processed_source_times)
                elif not prs:
                    next_watermark = now
                else:
                    next_watermark = None

                if next_watermark is not None:
                    # GitHub does not provide a stable tie-breaker for PRs
                    # sharing the same updated_at second.  Keep the timestamp
                    # cursor only; re-reading same-timestamp rows is safe
                    # because PR persistence is an idempotent upsert.
                    state_doc[state_key] = {
                        "source_updated_at": next_watermark.isoformat(),
                        "last_sync_completed_at": now.isoformat(),
                        "last_sync_count": count,
                        "last_sync_limited": bool(
                            processing_failed
                            or (max_items and len(prs) >= max_items)
                        ),
                    }
                    await self._save_sync_state(state_doc)
            await self.db.commit()
        except Exception as e:
            logger.error(f"Failed to commit PR data: {e}")
            await self.db.rollback()
            # Do not let the durable task be marked completed after a commit
            # failure.  Raising here sends the task through CollectorWorker's
            # retry/dead-letter path instead of silently losing the whole
            # batch.
            raise

        logger.info(f"Collected {count} PRs for {owner}/{repo}")
        return count

    async def _load_sync_state(self) -> dict[str, Any]:
        result = await self.db.execute(
            select(ProjectDashboardConfig).where(
                ProjectDashboardConfig.config_key == PR_SYNC_STATE_KEY
            )
        )
        row = result.scalar_one_or_none()
        value = row.config_value if row else {}
        return dict(value) if isinstance(value, dict) else {}

    async def _save_sync_state(self, state_doc: dict[str, Any]) -> None:
        result = await self.db.execute(
            select(ProjectDashboardConfig).where(
                ProjectDashboardConfig.config_key == PR_SYNC_STATE_KEY
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            self.db.add(
                ProjectDashboardConfig(
                    config_key=PR_SYNC_STATE_KEY,
                    config_value=state_doc,
                    description="PR pipeline GitHub updated_at watermarks",
                )
            )
        else:
            row.config_value = state_doc

    def _source_updated_at(self, pr: dict[str, Any]) -> datetime | None:
        return self._parse_datetime(pr.get("updated_at") or pr.get("created_at"))

    async def collect_single_pr(
        self,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> PullRequest | None:
        try:
            pr = await self.github.get_pr_detail(owner, repo, pr_number)
            pr["commits"] = await self.github.get_pr_commits(owner, repo, pr_number)
            reviews = await self.github.get_pr_reviews(owner, repo, pr_number)
            files = await self.github.get_pr_files(owner, repo, pr_number)

            db_pr = await self._upsert_pr(pr, owner, repo, reviews, files)

            await self.db.commit()
            return db_pr
        except GitHubRateLimitError as e:
            logger.error(f"Rate limit exceeded for PR #{pr_number}: {e}")
            await self.db.rollback()
            return None
        except GitHubAPIError as e:
            logger.error(f"API error for PR #{pr_number}: {e}")
            await self.db.rollback()
            return None
        except Exception as e:
            logger.error(f"Unexpected error for PR #{pr_number}: {e}", exc_info=True)
            await self.db.rollback()
            return None

    async def _upsert_pr(
        self,
        pr: dict[str, Any],
        owner: str,
        repo: str,
        reviews: list[dict[str, Any]],
        files: list[dict[str, Any]],
    ) -> PullRequest | None:
        pr_number = pr.get("number")
        if not pr_number:
            logger.warning("PR missing number, skipping")
            return None

        review_status = self.calculate_review_status(reviews)
        ci_status, ci_workflow_run_id, ci_started_at, ci_completed_at = await self._get_ci_status_for_sha(
            pr.get("head_sha") or (pr.get("head", {}) or {}).get("sha"),
            owner,
            repo,
        )
        pipeline_stage = self.calculate_pipeline_stage(
            pr=pr, ci_status=ci_status, review_status=review_status
        )

        first_review_at = None
        first_approved_at = None
        for review in reviews:
            state = review.get("state", "")
            submitted_at_str = review.get("submitted_at")
            if state == "PENDING":
                continue
            submitted_at = self._parse_datetime(submitted_at_str)
            if submitted_at:
                if first_review_at is None or submitted_at < first_review_at:
                    first_review_at = submitted_at
                if state == "APPROVED":
                    if first_approved_at is None or submitted_at < first_approved_at:
                        first_approved_at = submitted_at

        reviewers_list = []
        for review in reviews:
            user = review.get("user", {})
            if user:
                reviewers_list.append({
                    "login": user.get("login", ""),
                    "avatar_url": user.get("avatar_url", ""),
                    "state": review.get("state", ""),
                })

        user_info = pr.get("user") or {}
        author = user_info.get("login", "")
        author_avatar_url = user_info.get("avatar_url", "")

        # Fetch author email from PR commits (best-effort, non-fatal)
        author_email = None
        commit_items = pr.get("commits")
        commits = commit_items if isinstance(commit_items, list) else []
        try:
            if not isinstance(commit_items, list):
                commits = await self.github.get_pr_commits(owner, repo, pr_number)
            if commits:
                for commit in commits:
                    commit_author_login = (commit.get("author") or {}).get("login", "")
                    if not commit_author_login or commit_author_login == author:
                        author_email = (commit.get("commit", {}).get("author", {}).get("email", ""))
                        if author_email:
                            break
        except GitHubRateLimitError:
            raise
        except Exception as e:
            logger.warning(f"Failed to fetch author email for PR #{pr_number}: {e}")

        # Download author avatar and store as base64 (best-effort, non-fatal)
        author_avatar_base64 = None
        if author_avatar_url:
            try:
                async with httpx.AsyncClient(timeout=10) as http:
                    resp = await http.get(author_avatar_url)
                    if resp.status_code == 200:
                        content_type = resp.headers.get("content-type", "image/png")
                        b64 = base64.b64encode(resp.content).decode("ascii")
                        encoded_avatar = f"data:{content_type};base64,{b64}"
                        if len(encoded_avatar) <= MAX_AVATAR_BASE64_LENGTH:
                            author_avatar_base64 = encoded_avatar
                        else:
                            logger.debug(
                                "Skipping oversized avatar cache for PR #%s (%d chars)",
                                pr_number,
                                len(encoded_avatar),
                            )
            except Exception as e:
                logger.warning(f"Failed to download avatar for PR #{pr_number} ({author}): {e}")

        head_info = pr.get("head", {}) or {}
        base_info = pr.get("base", {}) or {}

        label_list = [label.get("name", "") for label in (pr.get("labels", []) or []) if isinstance(label, dict)]

        additions = pr.get("additions", 0) or 0
        deletions = pr.get("deletions", 0) or 0
        changed_files = pr.get("changed_files", 0) or 0

        total_additions = sum(f.get("additions", 0) for f in files) if files and additions == 0 else additions
        total_deletions = sum(f.get("deletions", 0) for f in files) if files and deletions == 0 else deletions
        total_changed = len(files) if files and changed_files == 0 else changed_files

        pr_state = pr.get("state", "open")
        merged_at = self._parse_datetime(pr.get("merged_at")) if pr.get("merged_at") else None
        closed_at = self._parse_datetime(pr.get("closed_at")) if pr.get("closed_at") else None

        if pr.get("merged") or merged_at:
            pr_state = "merged"

        stmt = select(PullRequest).where(
            PullRequest.pr_number == pr_number,
            PullRequest.owner == owner,
            PullRequest.repo == repo,
        )
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()

        pr_data = {
            "number": pr_number,
            "title": pr.get("title", ""),
            "body": pr.get("body") or "",
            "state": pr.get("state", ""),
            "html_url": pr.get("html_url", ""),
            "created_at": pr.get("created_at", ""),
            "updated_at": pr.get("updated_at", ""),
            "head": head_info,
            "base": base_info,
            "user": user_info,
            "labels": pr.get("labels", []),
            "draft": pr.get("draft", False),
            "merged": pr.get("merged", False),
            "merged_at": pr.get("merged_at"),
            "closed_at": pr.get("closed_at"),
            "additions": total_additions,
            "deletions": total_deletions,
            "changed_files": total_changed,
            "reviews": reviews,
            "commits": commits,
            "files_count": len(files),
        }

        if existing:
            existing.title = pr.get("title", "")
            existing.author = author
            existing.author_avatar_url = author_avatar_url
            existing.author_email = author_email or existing.author_email
            existing.author_avatar_base64 = author_avatar_base64
            existing.html_url = pr.get("html_url", "")
            existing.state = pr_state
            existing.is_draft = pr.get("draft", False) or False
            existing.labels = label_list
            existing.head_branch = head_info.get("ref", "")
            existing.head_sha = head_info.get("sha", "")
            existing.base_branch = base_info.get("ref", "")
            existing.additions = total_additions
            existing.deletions = total_deletions
            existing.changed_files = total_changed
            existing.pipeline_stage = pipeline_stage
            existing.review_status = review_status
            existing.reviewers = reviewers_list
            existing.ci_status = ci_status
            existing.ci_workflow_run_id = ci_workflow_run_id
            existing.first_review_at = first_review_at
            existing.first_approved_at = first_approved_at
            existing.ci_started_at = ci_started_at
            existing.ci_completed_at = ci_completed_at
            existing.merged_at = merged_at
            existing.closed_at = closed_at
            existing.data = pr_data
            logger.debug(f"Updated PR #{pr_number} for {owner}/{repo}")
            return existing
        else:
            new_pr = PullRequest(
                pr_number=pr_number,
                owner=owner,
                repo=repo,
                title=pr.get("title", ""),
                author=author,
                author_avatar_url=author_avatar_url,
                author_avatar_base64=author_avatar_base64,
                author_email=author_email,
                html_url=pr.get("html_url", ""),
                state=pr_state,
                is_draft=pr.get("draft", False) or False,
                labels=label_list,
                head_branch=head_info.get("ref", ""),
                head_sha=head_info.get("sha", ""),
                base_branch=base_info.get("ref", ""),
                additions=total_additions,
                deletions=total_deletions,
                changed_files=total_changed,
                pipeline_stage=pipeline_stage,
                review_status=review_status,
                reviewers=reviewers_list,
                ci_status=ci_status,
                ci_workflow_run_id=ci_workflow_run_id,
                first_review_at=first_review_at,
                first_approved_at=first_approved_at,
                ci_started_at=ci_started_at,
                ci_completed_at=ci_completed_at,
                merged_at=merged_at,
                closed_at=closed_at,
                created_at=self._parse_datetime(pr.get("created_at")) or datetime.now(UTC),
                data=pr_data,
            )
            self.db.add(new_pr)
            logger.debug(f"Created PR #{pr_number} for {owner}/{repo}")
            return new_pr

    @staticmethod
    def calculate_pipeline_stage(
        pr: dict[str, Any] | None = None,
        db_pr: PullRequest | None = None,
        ci_status: str | None = None,
        review_status: str | None = None,
    ) -> str:
        state = None
        if db_pr:
            state = db_pr.state
            if ci_status is None:
                ci_status = db_pr.ci_status
            if review_status is None:
                review_status = db_pr.review_status
        elif pr:
            state = pr.get("state", "open")
            if pr.get("merged") or pr.get("merged_at"):
                state = "merged"

        if state == "merged":
            return "merged"
        if state == "closed":
            return "closed"
        if state == "open":
            if ci_status == "failure":
                return "ci_failed"
            if ci_status == "in_progress":
                return "ci_running"
            if ci_status == "success" and review_status == "approved":
                return "merging"
            if ci_status == "success":
                return "ci_passed"
            if review_status == "approved":
                return "approved"
            if review_status in ("changes_requested", "reviewing"):
                return "reviewing"
            return "submitted"
        return "submitted"

    @staticmethod
    def calculate_review_status(reviews: list[dict[str, Any]]) -> str:
        if not reviews:
            return "none"

        has_approved = False
        has_changes_requested = False
        has_reviewing = False

        latest_by_user: dict[str, str] = {}
        for review in reviews:
            user = review.get("user", {})
            login = user.get("login", "")
            state = review.get("state", "")
            if not login or state == "PENDING" or state == "COMMENTED":
                continue
            latest_by_user[login] = state

        for _login, state in latest_by_user.items():
            if state == "APPROVED":
                has_approved = True
            elif state == "CHANGES_REQUESTED":
                has_changes_requested = True
            else:
                has_reviewing = True

        if has_approved:
            return "approved"
        if has_changes_requested:
            return "changes_requested"
        if has_reviewing:
            return "reviewing"
        return "none"

    async def _get_ci_status_for_sha(
        self,
        head_sha: str | None,
        owner: str | None = None,
        repo: str | None = None,
    ) -> tuple[str | None, int | None, datetime | None, datetime | None]:
        if not head_sha:
            return (None, None, None, None)

        stmt = (
            select(CIResult)
            .where(
                CIResult.head_sha == head_sha,
            )
            .order_by(CIResult.created_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        ci_result = result.scalar_one_or_none()

        if ci_result:
            ci_status = None
            if ci_result.status == "completed":
                conclusion = ci_result.conclusion
                if conclusion == "success":
                    ci_status = "success"
                elif conclusion == "failure":
                    ci_status = "failure"
                elif conclusion == "cancelled":
                    ci_status = "cancelled"
                else:
                    ci_status = conclusion
            elif ci_result.status == "in_progress":
                ci_status = "in_progress"
            elif ci_result.status == "queued":
                ci_status = "queued"
            else:
                ci_status = ci_result.status

            return (
                ci_status,
                ci_result.run_id,
                ci_result.started_at,
                ci_result.completed_at,
            )

        if owner and repo:
            try:
                ci_status, run_id, started_at, completed_at = await self._get_ci_status_from_github(
                    owner, repo, head_sha
                )
                if ci_status:
                    return (ci_status, run_id, started_at, completed_at)
            except GitHubRateLimitError:
                raise
            except Exception as e:
                logger.warning(f"Failed to fetch check runs from GitHub API for SHA {head_sha[:8]}: {e}")

        return (None, None, None, None)

    async def _get_ci_status_from_github(
        self,
        owner: str,
        repo: str,
        head_sha: str,
    ) -> tuple[str | None, int | None, datetime | None, datetime | None]:
        """Fetch CI status from GitHub check runs API as a fallback when DB has no record."""
        check_runs = await self.github.get_check_runs_for_sha(owner, repo, head_sha)
        if not check_runs:
            return (None, None, None, None)

        has_in_progress = False
        has_queued = False
        has_failure = False
        has_success = False
        started_at: datetime | None = None
        completed_at: datetime | None = None
        run_id: int | None = None

        for run in check_runs:
            status = run.get("status", "")
            conclusion = run.get("conclusion")
            run_started = self._parse_datetime(run.get("started_at"))
            run_completed = self._parse_datetime(run.get("completed_at"))

            if run_started and (started_at is None or run_started < started_at):
                started_at = run_started
            if run_completed and (completed_at is None or run_completed > completed_at):
                completed_at = run_completed

            if run_id is None:
                run_id = run.get("run_id")

            if status == "in_progress":
                has_in_progress = True
            elif status == "queued":
                has_queued = True
            elif status == "completed":
                if conclusion == "failure":
                    has_failure = True
                elif conclusion == "success":
                    has_success = True

        if has_in_progress or has_queued:
            ci_status = "in_progress"
        elif has_failure:
            ci_status = "failure"
        elif has_success:
            ci_status = "success"
        else:
            ci_status = None

        return (ci_status, run_id, started_at, completed_at)

    def _parse_datetime(self, dt_string: str | None) -> datetime | None:
        if not dt_string:
            return None
        try:
            dt_string = dt_string.replace("Z", "+00:00")
            return datetime.fromisoformat(dt_string)
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse datetime '{dt_string}': {e}")
            return None
