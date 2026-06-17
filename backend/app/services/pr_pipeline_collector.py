import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CIResult, PullRequest
from app.services.github_client import GitHubAPIError, GitHubClient, GitHubRateLimitError

logger = logging.getLogger(__name__)


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
    ) -> int:
        if since is None:
            since = datetime.now(UTC) - timedelta(days=days_back)

        now = datetime.now(UTC)
        prs = await self.github.get_pull_requests_by_date_range(owner, repo, since, now)
        logger.info(f"Fetched {len(prs)} PRs for {owner}/{repo} since {since.isoformat()}")

        count = 0
        for pr in prs:
            try:
                pr_number = pr["number"]
                reviews = await self.github.get_pr_reviews(owner, repo, pr_number)
                files = await self.github.get_pr_files(owner, repo, pr_number)

                if "additions" not in pr or pr.get("additions") is None:
                    try:
                        detail = await self.github.get_pr_detail(owner, repo, pr_number)
                        pr = {**pr, **detail}
                    except Exception as e:
                        logger.warning(f"Failed to fetch PR detail for #{pr_number}: {e}")

                db_pr = await self._upsert_pr(pr, owner, repo, reviews, files)
                if db_pr:
                    count += 1
            except GitHubRateLimitError as e:
                logger.error(f"Rate limit exceeded while processing PRs: {e}")
                break
            except GitHubAPIError as e:
                logger.error(f"API error processing PR #{pr.get('number', '?')}: {e}")
                continue
            except Exception as e:
                logger.error(f"Unexpected error processing PR #{pr.get('number', '?')}: {e}", exc_info=True)
                continue

        try:
            await self.db.commit()
        except Exception as e:
            logger.error(f"Failed to commit PR data: {e}")
            await self.db.rollback()
            return 0

        logger.info(f"Collected {count} PRs for {owner}/{repo}")
        return count

    async def collect_single_pr(
        self,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> PullRequest | None:
        try:
            pr = await self.github.get_pr_detail(owner, repo, pr_number)
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
            pr.get("head_sha") or (pr.get("head", {}) or {}).get("sha")
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
                    "state": review.get("state", ""),
                })

        user_info = pr.get("user") or {}
        author = user_info.get("login", "")
        author_avatar_url = user_info.get("avatar_url", "")

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
            "files_count": len(files),
        }

        if existing:
            existing.title = pr.get("title", "")
            existing.author = author
            existing.author_avatar_url = author_avatar_url
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

        for login, state in latest_by_user.items():
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
    ) -> tuple[str | None, int | None, datetime | None, datetime | None]:
        if not head_sha:
            return (None, None, None, None)

        stmt = (
            select(CIResult)
            .where(
                CIResult.event == "pull_request",
                CIResult.head_sha == head_sha,
            )
            .order_by(CIResult.created_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        ci_result = result.scalar_one_or_none()

        if not ci_result:
            return (None, None, None, None)

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

    def _parse_datetime(self, dt_string: str | None) -> datetime | None:
        if not dt_string:
            return None
        try:
            dt_string = dt_string.replace("Z", "+00:00")
            return datetime.fromisoformat(dt_string)
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse datetime '{dt_string}': {e}")
            return None
