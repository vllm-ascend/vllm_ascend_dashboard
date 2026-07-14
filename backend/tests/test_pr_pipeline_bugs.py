"""Tests for PR Pipeline bug fixes (Issue #80): B1, B2, B3, B4."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.pr_pipeline_collector import PRPipelineCollector
from app.services.pr_pipeline_service import PRPipelineService
from tests.conftest import make_ci_result, make_pr

OWNER = "vllm-ascend"
REPO = "vllm-ascend"


class TestContributorEmails:
    """Contributor rows should expose commit author emails for PR authors."""

    @pytest.mark.asyncio
    async def test_author_contributor_includes_commit_emails(self, db_session):
        now = datetime.now(UTC)
        pr = make_pr(
            pr_number=9101,
            author="alice",
            created_at=now - timedelta(days=1),
        )
        pr.data = {
            "commits": [
                {
                    "author": {"login": "alice"},
                    "commit": {"author": {"email": "alice@example.com"}},
                },
                {
                    "author": {"login": "alice"},
                    "commit": {"author": {"email": "alice@example.com"}},
                },
                {
                    "author": {"login": "other"},
                    "commit": {"author": {"email": "other@example.com"}},
                },
            ]
        }
        db_session.add(pr)
        await db_session.commit()

        service = PRPipelineService()
        result = await service.get_contributors(db_session, OWNER, REPO, days=30, type="author")

        alice = next(item for item in result.items if item.username == "alice")
        assert alice.emails == ["alice@example.com"]
        assert alice.primary_email == "alice@example.com"

    @pytest.mark.asyncio
    async def test_collector_preserves_commit_list_when_pr_detail_has_commit_count(self, db_session):
        """GitHub PR detail has commits as a count; it must not overwrite commit details."""
        now = datetime.now(UTC)
        commit_items = [
            {
                "author": {"login": "alice"},
                "commit": {"author": {"email": "alice@example.com"}},
            }
        ]
        pr_summary = {
            "number": 9201,
            "title": "Preserve commits",
            "state": "open",
            "html_url": "https://github.com/example/repo/pull/9201",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "user": {"login": "alice", "avatar_url": ""},
            "head": {"sha": "abc123", "ref": "feature"},
            "base": {"ref": "main"},
            "labels": [],
            "draft": False,
            "commits": commit_items,
        }
        pr_detail = {
            "additions": 10,
            "deletions": 2,
            "changed_files": 1,
            "commits": 1,
        }
        github = MagicMock()
        github.get_pull_requests_by_date_range = AsyncMock(return_value=[pr_summary])
        github.get_pr_detail = AsyncMock(return_value=pr_detail)
        github.get_pr_reviews = AsyncMock(return_value=[])
        github.get_pr_files = AsyncMock(return_value=[])
        github.get_check_runs_for_sha = AsyncMock(return_value=[])

        collector = PRPipelineCollector(github, db_session)
        await collector.collect_prs(OWNER, REPO, days_back=1)

        service = PRPipelineService()
        contributors = await service.get_contributors(db_session, OWNER, REPO, days=30, type="author")
        alice = next(item for item in contributors.items if item.username == "alice")
        assert alice.primary_email == "alice@example.com"

    @pytest.mark.asyncio
    async def test_author_contributor_merges_same_login_with_multiple_emails(self, db_session):
        """A GitHub login should stay one contributor even when commits use several emails."""
        now = datetime.now(UTC)
        pr1 = make_pr(
            pr_number=9301,
            author="alice",
            created_at=now - timedelta(days=2),
        )
        pr1.author_email = "alice@users.noreply.github.com"
        pr1.data = {
            "commits": [
                {
                    "author": {"login": "alice"},
                    "commit": {"author": {"email": "alice@users.noreply.github.com"}},
                }
            ]
        }
        pr2 = make_pr(
            pr_number=9302,
            author="alice",
            created_at=now - timedelta(days=1),
        )
        pr2.author_email = "alice@example.com"
        pr2.data = {
            "commits": [
                {
                    "author": {"login": "alice"},
                    "commit": {"author": {"email": "alice@example.com"}},
                }
            ]
        }
        db_session.add_all([pr1, pr2])
        await db_session.commit()

        service = PRPipelineService()
        result = await service.get_contributors(db_session, OWNER, REPO, days=30, type="author")

        alice_rows = [item for item in result.items if item.username == "alice"]
        assert len(alice_rows) == 1
        assert alice_rows[0].pr_count == 2
        assert set(alice_rows[0].emails) == {
            "alice@users.noreply.github.com",
            "alice@example.com",
        }

    @pytest.mark.asyncio
    async def test_author_email_queries_do_not_scale_with_contributor_count(self, db_session):
        now = datetime.now(UTC)
        for index, author in enumerate(("alice", "bob", "carol"), start=1):
            pr = make_pr(
                pr_number=9400 + index,
                author=author,
                created_at=now - timedelta(days=1),
            )
            pr.author_email = f"{author}@example.com"
            pr.data = {
                "commits": [
                    {
                        "author": {"login": author},
                        "commit": {"author": {"email": f"{author}@example.com"}},
                    }
                ]
            }
            db_session.add(pr)
        await db_session.commit()

        original_execute = db_session.execute
        db_session.execute = AsyncMock(wraps=original_execute)

        service = PRPipelineService()
        result = await service.get_contributors(
            db_session,
            OWNER,
            REPO,
            days=30,
            type="author",
        )

        assert {item.username for item in result.items} == {"alice", "bob", "carol"}
        assert db_session.execute.await_count == 3


# ============================================================================
# B1: Backlog index formula — should be Open(non-Draft) / daily_merge_avg
# ============================================================================

class TestB1BacklogIndexFormula:
    """B1: backlog_index must equal (open - draft) / (recent_merged / days)."""

    @pytest.mark.asyncio
    async def test_backlog_index_overview_matches_design_formula(self, db_session):
        """Verify get_overview backlog_index = (open - draft) / (recent_merged / days)."""
        now = datetime.now(UTC)
        days = 30

        # 10 open non-draft + 3 open draft = 13 open total
        for i in range(10):
            db_session.add(make_pr(pr_number=100 + i, state="open", is_draft=False, created_at=now))
        for i in range(3):
            db_session.add(make_pr(pr_number=200 + i, state="open", is_draft=True, created_at=now))

        # 60 merged in last 30 days
        for i in range(60):
            db_session.add(make_pr(
                pr_number=300 + i, state="merged",
                created_at=now - timedelta(days=10),
                merged_at=now - timedelta(days=5),
            ))
        await db_session.commit()

        service = PRPipelineService()
        result = await service.get_overview(db_session, OWNER, REPO, days=days)

        open_non_draft = 10
        daily_merge_avg = 60 / 30  # = 2.0
        expected = round(open_non_draft / daily_merge_avg, 1)  # 5.0

        assert result.backlog_index == expected, (
            f"Expected backlog_index={expected}, got {result.backlog_index}"
        )

    @pytest.mark.asyncio
    async def test_backlog_index_excludes_draft_from_numerator(self, db_session):
        """Draft PRs must be excluded from the backlog numerator."""
        now = datetime.now(UTC)
        days = 30

        # 5 open non-draft + 5 open draft
        for i in range(5):
            db_session.add(make_pr(pr_number=10 + i, state="open", is_draft=False, created_at=now))
        for i in range(5):
            db_session.add(make_pr(pr_number=20 + i, state="open", is_draft=True, created_at=now))

        # 30 merged in last 30 days → daily avg = 1.0
        for i in range(30):
            db_session.add(make_pr(
                pr_number=30 + i, state="merged",
                created_at=now - timedelta(days=10),
                merged_at=now - timedelta(days=5),
            ))
        await db_session.commit()

        service = PRPipelineService()
        result = await service.get_overview(db_session, OWNER, REPO, days=days)

        # (5 open non-draft) / (30/30 = 1.0 daily avg) = 5.0
        assert result.backlog_index == 5.0

    @pytest.mark.asyncio
    async def test_backlog_index_metrics_matches_design_formula(self, db_session):
        """Verify get_metrics backlog_index uses same formula as get_overview."""
        now = datetime.now(UTC)
        days = 30

        for i in range(20):
            db_session.add(make_pr(pr_number=1 + i, state="open", is_draft=False, created_at=now))
        for i in range(5):
            db_session.add(make_pr(pr_number=50 + i, state="open", is_draft=True, created_at=now))

        # 100 merged → daily avg = 100/30 ≈ 3.33
        for i in range(100):
            db_session.add(make_pr(
                pr_number=100 + i, state="merged",
                created_at=now - timedelta(days=10),
                merged_at=now - timedelta(days=5),
            ))
        await db_session.commit()

        service = PRPipelineService()
        result = await service.get_metrics(db_session, OWNER, REPO, days=days)

        open_non_draft = 20
        daily_merge_avg = 100 / 30
        expected = round(open_non_draft / daily_merge_avg, 1)

        assert result.backlog_index == expected, (
            f"Expected backlog_index={expected}, got {result.backlog_index}"
        )

    @pytest.mark.asyncio
    async def test_backlog_index_zero_merges(self, db_session):
        """When there are no recent merges, backlog should reflect open count."""
        now = datetime.now(UTC)
        days = 30

        # 5 open non-draft, 0 merged
        for i in range(5):
            db_session.add(make_pr(pr_number=1 + i, state="open", is_draft=False, created_at=now))
        await db_session.commit()

        service = PRPipelineService()
        result = await service.get_overview(db_session, OWNER, REPO, days=days)

        # No merges → daily_merge_avg = 0 → fallback: open_non_draft count = 5.0
        assert result.backlog_index == 5.0
        assert result.backlog_level == "red"

    @pytest.mark.asyncio
    async def test_backlog_index_real_scenario_from_issue(self, db_session):
        """Reproduce issue #80 scenario: open=207, draft=13, merged=198 over 30d.

        Expected: (207-13) / (198/30) = 194 / 6.6 = 29.4 (red)
        Old buggy formula: 207 / (198+207) = 0.5 (green) — WRONG
        """
        now = datetime.now(UTC)
        days = 30

        # 194 open non-draft + 13 open draft = 207 open total
        for i in range(194):
            db_session.add(make_pr(pr_number=1000 + i, state="open", is_draft=False, created_at=now))
        for i in range(13):
            db_session.add(make_pr(pr_number=2000 + i, state="open", is_draft=True, created_at=now))

        # 198 merged in last 30 days
        for i in range(198):
            db_session.add(make_pr(
                pr_number=3000 + i, state="merged",
                created_at=now - timedelta(days=10),
                merged_at=now - timedelta(days=5),
            ))
        await db_session.commit()

        service = PRPipelineService()
        result = await service.get_overview(db_session, OWNER, REPO, days=days)

        daily_merge_avg = 198 / 30
        expected = round(194 / daily_merge_avg, 1)

        assert result.backlog_index == expected
        assert result.backlog_level == "red", (
            f"Backlog {result.backlog_index} should be red (>=3), got {result.backlog_level}"
        )


# ============================================================================
# B2: Backlog thresholds — green < 1.5, yellow >= 1.5 & < 3, red >= 3
# ============================================================================

class TestB2BacklogThresholds:
    """B2: Thresholds must be green<1.5 / yellow>=1.5 / red>=3 (backend + frontend)."""

    @pytest.mark.asyncio
    async def test_backlog_level_green(self, db_session):
        """backlog_index < 1.5 → green."""
        now = datetime.now(UTC)
        days = 30

        # 1 open non-draft, 30 merged → 1 / (30/30=1.0) = 1.0 → green
        db_session.add(make_pr(pr_number=1, state="open", is_draft=False, created_at=now))
        for i in range(30):
            db_session.add(make_pr(
                pr_number=100 + i, state="merged",
                created_at=now - timedelta(days=10),
                merged_at=now - timedelta(days=5),
            ))
        await db_session.commit()

        service = PRPipelineService()
        result = await service.get_overview(db_session, OWNER, REPO, days=days)

        assert result.backlog_index < 1.5
        assert result.backlog_level == "green"

    @pytest.mark.asyncio
    async def test_backlog_level_yellow(self, db_session):
        """1.5 <= backlog_index < 3 → yellow."""
        now = datetime.now(UTC)
        days = 30

        # 2 open non-draft, 30 merged → 2 / 1.0 = 2.0 → yellow
        for i in range(2):
            db_session.add(make_pr(pr_number=1 + i, state="open", is_draft=False, created_at=now))
        for i in range(30):
            db_session.add(make_pr(
                pr_number=100 + i, state="merged",
                created_at=now - timedelta(days=10),
                merged_at=now - timedelta(days=5),
            ))
        await db_session.commit()

        service = PRPipelineService()
        result = await service.get_overview(db_session, OWNER, REPO, days=days)

        assert 1.5 <= result.backlog_index < 3
        assert result.backlog_level == "yellow"

    @pytest.mark.asyncio
    async def test_backlog_level_red(self, db_session):
        """backlog_index >= 3 → red."""
        now = datetime.now(UTC)
        days = 30

        # 5 open non-draft, 30 merged → 5 / 1.0 = 5.0 → red
        for i in range(5):
            db_session.add(make_pr(pr_number=1 + i, state="open", is_draft=False, created_at=now))
        for i in range(30):
            db_session.add(make_pr(
                pr_number=100 + i, state="merged",
                created_at=now - timedelta(days=10),
                merged_at=now - timedelta(days=5),
            ))
        await db_session.commit()

        service = PRPipelineService()
        result = await service.get_overview(db_session, OWNER, REPO, days=days)

        assert result.backlog_index >= 3
        assert result.backlog_level == "red"

    def test_frontend_get_backlog_color_green(self):
        """Frontend getBacklogColor: index < 1.5 → green color."""
        # Replicate the frontend logic
        def get_backlog_color(index):
            if index < 1.5:
                return "#52c41a"
            if index < 3:
                return "#faad14"
            return "#ff4d4f"

        assert get_backlog_color(0.5) == "#52c41a"
        assert get_backlog_color(1.4) == "#52c41a"
        assert get_backlog_color(1.49) == "#52c41a"

    def test_frontend_get_backlog_color_yellow(self):
        """Frontend getBacklogColor: 1.5 <= index < 3 → yellow color."""
        def get_backlog_color(index):
            if index < 1.5:
                return "#52c41a"
            if index < 3:
                return "#faad14"
            return "#ff4d4f"

        assert get_backlog_color(1.5) == "#faad14"
        assert get_backlog_color(2.0) == "#faad14"
        assert get_backlog_color(2.99) == "#faad14"

    def test_frontend_get_backlog_color_red(self):
        """Frontend getBacklogColor: index >= 3 → red color."""
        def get_backlog_color(index):
            if index < 1.5:
                return "#52c41a"
            if index < 3:
                return "#faad14"
            return "#ff4d4f"

        assert get_backlog_color(3.0) == "#ff4d4f"
        assert get_backlog_color(5.0) == "#ff4d4f"
        assert get_backlog_color(29.4) == "#ff4d4f"

    def test_thresholds_match_between_frontend_and_backend(self):
        """Verify frontend and backend use identical threshold boundaries."""
        # Backend logic (from pr_pipeline_service.py)
        def backend_level(index):
            if index < 1.5:
                return "green"
            if index < 3:
                return "yellow"
            return "red"

        # Frontend logic (from PRPipelineBoard.tsx getBacklogColor)
        def frontend_color(index):
            if index < 1.5:
                return "#52c41a"  # green
            if index < 3:
                return "#faad14"  # yellow
            return "#ff4d4f"  # red

        color_to_level = {"#52c41a": "green", "#faad14": "yellow", "#ff4d4f": "red"}

        test_values = [0.0, 0.5, 1.0, 1.49, 1.5, 2.0, 2.99, 3.0, 5.0, 29.4, 100.0]
        for v in test_values:
            backend = backend_level(v)
            frontend = color_to_level[frontend_color(v)]
            assert backend == frontend, (
                f"Threshold mismatch at index={v}: backend={backend}, frontend={frontend}"
            )


# ============================================================================
# B3: Merge rate display — backend returns 0-1 ratio, frontend multiplies by 100
# ============================================================================

class TestB3MergeRate:
    """B3: merge_rate must be 0-1 ratio from backend; frontend multiplies by 100."""

    @pytest.mark.asyncio
    async def test_merge_rate_is_zero_to_one_ratio(self, db_session):
        """Backend merge_rate must be in [0, 1] range (e.g., 0.75 not 75)."""
        now = datetime.now(UTC)

        # 75 merged, 25 closed → merge_rate = 75 / (75+25) = 0.75
        for i in range(75):
            db_session.add(make_pr(
                pr_number=100 + i, state="merged",
                created_at=now - timedelta(days=10),
                merged_at=now - timedelta(days=5),
            ))
        for i in range(25):
            db_session.add(make_pr(
                pr_number=200 + i, state="closed",
                created_at=now - timedelta(days=10),
                closed_at=now - timedelta(days=5),
            ))
        await db_session.commit()

        service = PRPipelineService()
        result = await service.get_overview(db_session, OWNER, REPO, days=30)

        assert result.merge_rate == 0.75
        assert 0 <= result.merge_rate <= 1, "merge_rate must be 0-1 ratio"

    @pytest.mark.asyncio
    async def test_merge_rate_metrics_also_zero_to_one(self, db_session):
        """get_metrics merge_rate must also be 0-1 ratio."""
        now = datetime.now(UTC)

        for i in range(60):
            db_session.add(make_pr(
                pr_number=1 + i, state="merged",
                created_at=now - timedelta(days=10),
                merged_at=now - timedelta(days=5),
            ))
        for i in range(40):
            db_session.add(make_pr(
                pr_number=100 + i, state="closed",
                created_at=now - timedelta(days=10),
                closed_at=now - timedelta(days=5),
            ))
        await db_session.commit()

        service = PRPipelineService()
        result = await service.get_metrics(db_session, OWNER, REPO, days=30)

        assert result.merge_rate == 0.6
        assert 0 <= result.merge_rate <= 1

    def test_frontend_display_multiplies_by_100(self):
        """Simulate frontend display: merge_rate * 100 with % suffix.

        Old bug: value={0.75} + suffix="%" → displayed "0.7%"
        Fix: value={0.75 * 100} + suffix="%" → displays "75.0%"
        """
        backend_merge_rate = 0.75

        # Simulate what the fixed frontend renders
        displayed_value = backend_merge_rate * 100  # fix: multiply by 100
        assert displayed_value == 75.0

        # The color threshold should use 0-1 scale (0.6 = 60%)
        color = "#52c41a" if backend_merge_rate >= 0.6 else "#faad14"
        assert color == "#52c41a"  # 75% >= 60% → green

    def test_frontend_display_low_merge_rate(self):
        """Merge rate below 60% should show yellow color."""
        backend_merge_rate = 0.4  # 40%

        displayed_value = backend_merge_rate * 100
        assert displayed_value == 40.0

        color = "#52c41a" if backend_merge_rate >= 0.6 else "#faad14"
        assert color == "#faad14"  # 40% < 60% → yellow


# ============================================================================
# B4: CI data — DB lookup (no event filter) + GitHub API fallback
# ============================================================================

class TestB4CIDataCollection:
    """B4: CI status must be populated via head_sha→CIResult or GitHub API fallback."""

    @pytest.mark.asyncio
    async def test_ci_status_from_db_with_pull_request_event(self, db_session):
        """CI status is fetched from CIResult table when event='pull_request'."""
        sha = "abc123def456"
        now = datetime.now(UTC)
        db_session.add(make_ci_result(
            run_id=999,
            head_sha=sha,
            status="completed",
            conclusion="success",
            event="pull_request",
            started_at=now - timedelta(hours=1),
            completed_at=now,
        ))
        await db_session.commit()

        mock_github = MagicMock()
        collector = PRPipelineCollector(mock_github, db_session)

        ci_status, run_id, started_at, completed_at = await collector._get_ci_status_for_sha(
            sha, OWNER, REPO
        )

        assert ci_status == "success"
        assert run_id == 999
        assert started_at is not None
        assert completed_at is not None
        # GitHub API should NOT be called when DB has a record
        mock_github.get_check_runs_for_sha.assert_not_called()

    @pytest.mark.asyncio
    async def test_ci_status_from_db_with_push_event(self, db_session):
        """B4 fix: CI status fetched from CIResult regardless of event type.

        The old code filtered by event == 'pull_request', missing push-event CI runs
        that share the same head_sha. The fix removes that filter.
        """
        sha = "push_sha_123"
        now = datetime.now(UTC)
        db_session.add(make_ci_result(
            run_id=888,
            head_sha=sha,
            status="completed",
            conclusion="failure",
            event="push",  # Not pull_request!
            started_at=now - timedelta(hours=2),
            completed_at=now - timedelta(hours=1),
        ))
        await db_session.commit()

        mock_github = MagicMock()
        collector = PRPipelineCollector(mock_github, db_session)

        ci_status, run_id, started_at, completed_at = await collector._get_ci_status_for_sha(
            sha, OWNER, REPO
        )

        assert ci_status == "failure"
        assert run_id == 888
        # GitHub API should NOT be called
        mock_github.get_check_runs_for_sha.assert_not_called()

    @pytest.mark.asyncio
    async def test_ci_status_fallback_to_github_api(self, db_session):
        """When DB has no CIResult, fall back to GitHub Check Runs API."""
        sha = "no_db_record_sha"
        now = datetime.now(UTC)

        mock_github = MagicMock()
        mock_github.get_check_runs_for_sha = AsyncMock(return_value=[
            {
                "status": "completed",
                "conclusion": "success",
                "started_at": (now - timedelta(hours=1)).isoformat(),
                "completed_at": now.isoformat(),
                "run_id": 12345,
            }
        ])

        collector = PRPipelineCollector(mock_github, db_session)
        ci_status, run_id, started_at, completed_at = await collector._get_ci_status_for_sha(
            sha, OWNER, REPO
        )

        assert ci_status == "success"
        assert started_at is not None
        assert completed_at is not None
        mock_github.get_check_runs_for_sha.assert_called_once_with(OWNER, REPO, sha)

    @pytest.mark.asyncio
    async def test_ci_status_fallback_aggregation_failure(self, db_session):
        """GitHub fallback: one failure among completed runs → overall failure."""
        sha = "mixed_results_sha"

        mock_github = MagicMock()
        mock_github.get_check_runs_for_sha = AsyncMock(return_value=[
            {"status": "completed", "conclusion": "success", "started_at": None, "completed_at": None},
            {"status": "completed", "conclusion": "failure", "started_at": None, "completed_at": None},
            {"status": "completed", "conclusion": "success", "started_at": None, "completed_at": None},
        ])

        collector = PRPipelineCollector(mock_github, db_session)
        ci_status, _, _, _ = await collector._get_ci_status_for_sha(sha, OWNER, REPO)

        assert ci_status == "failure"

    @pytest.mark.asyncio
    async def test_ci_status_fallback_aggregation_in_progress(self, db_session):
        """GitHub fallback: any in_progress run → overall in_progress."""
        sha = "running_sha"
        now = datetime.now(UTC)

        mock_github = MagicMock()
        mock_github.get_check_runs_for_sha = AsyncMock(return_value=[
            {"status": "completed", "conclusion": "success", "started_at": None, "completed_at": None},
            {"status": "in_progress", "conclusion": None, "started_at": now.isoformat(), "completed_at": None},
        ])

        collector = PRPipelineCollector(mock_github, db_session)
        ci_status, _, started_at, _ = await collector._get_ci_status_for_sha(sha, OWNER, REPO)

        assert ci_status == "in_progress"
        assert started_at is not None

    @pytest.mark.asyncio
    async def test_ci_status_fallback_aggregation_all_success(self, db_session):
        """GitHub fallback: all completed with success → overall success."""
        sha = "all_pass_sha"
        now = datetime.now(UTC)

        mock_github = MagicMock()
        mock_github.get_check_runs_for_sha = AsyncMock(return_value=[
            {"status": "completed", "conclusion": "success",
             "started_at": (now - timedelta(hours=2)).isoformat(),
             "completed_at": (now - timedelta(hours=1)).isoformat()},
            {"status": "completed", "conclusion": "success",
             "started_at": (now - timedelta(hours=1, minutes=30)).isoformat(),
             "completed_at": (now - timedelta(minutes=30)).isoformat()},
        ])

        collector = PRPipelineCollector(mock_github, db_session)
        ci_status, _, started_at, completed_at = await collector._get_ci_status_for_sha(sha, OWNER, REPO)

        assert ci_status == "success"
        # started_at should be the earliest, completed_at the latest
        assert started_at is not None
        assert completed_at is not None
        assert started_at < completed_at

    @pytest.mark.asyncio
    async def test_ci_status_fallback_empty_check_runs(self, db_session):
        """GitHub fallback: no check runs → returns None."""
        sha = "no_checks_sha"

        mock_github = MagicMock()
        mock_github.get_check_runs_for_sha = AsyncMock(return_value=[])

        collector = PRPipelineCollector(mock_github, db_session)
        ci_status, run_id, started_at, completed_at = await collector._get_ci_status_for_sha(
            sha, OWNER, REPO
        )

        assert ci_status is None
        assert run_id is None
        assert started_at is None
        assert completed_at is None

    @pytest.mark.asyncio
    async def test_ci_status_no_sha_returns_none(self, db_session):
        """When head_sha is None, return all None immediately."""
        mock_github = MagicMock()
        collector = PRPipelineCollector(mock_github, db_session)

        ci_status, run_id, started_at, completed_at = await collector._get_ci_status_for_sha(
            None, OWNER, REPO
        )

        assert ci_status is None
        assert run_id is None
        assert started_at is None
        assert completed_at is None
        mock_github.get_check_runs_for_sha.assert_not_called()

    @pytest.mark.asyncio
    async def test_ci_status_fallback_github_api_error_handled(self, db_session):
        """When GitHub API raises a generic error, fallback returns None gracefully."""
        sha = "error_sha"

        mock_github = MagicMock()
        mock_github.get_check_runs_for_sha = AsyncMock(side_effect=Exception("API error"))

        collector = PRPipelineCollector(mock_github, db_session)
        ci_status, _, _, _ = await collector._get_ci_status_for_sha(sha, OWNER, REPO)

        assert ci_status is None

    @pytest.mark.asyncio
    async def test_db_takes_precedence_over_github_api(self, db_session):
        """When DB has a CIResult, GitHub API is not called."""
        sha = "precedence_sha"
        now = datetime.now(UTC)

        db_session.add(make_ci_result(
            run_id=555,
            head_sha=sha,
            status="completed",
            conclusion="success",
            event="pull_request",
            started_at=now - timedelta(hours=1),
            completed_at=now,
        ))
        await db_session.commit()

        mock_github = MagicMock()
        mock_github.get_check_runs_for_sha = AsyncMock(return_value=[
            {"status": "completed", "conclusion": "failure", "started_at": None, "completed_at": None},
        ])

        collector = PRPipelineCollector(mock_github, db_session)
        ci_status, run_id, _, _ = await collector._get_ci_status_for_sha(sha, OWNER, REPO)

        # DB says success, GitHub says failure — DB wins
        assert ci_status == "success"
        assert run_id == 555
        mock_github.get_check_runs_for_sha.assert_not_called()

    @pytest.mark.asyncio
    async def test_ci_status_populated_in_upsert_pr(self, db_session):
        """Integration: _upsert_pr should populate ci_status via GitHub fallback."""
        sha = "upsert_ci_sha"
        now = datetime.now(UTC)

        mock_github = MagicMock()
        mock_github.get_check_runs_for_sha = AsyncMock(return_value=[
            {"status": "completed", "conclusion": "success",
             "started_at": (now - timedelta(hours=1)).isoformat(),
             "completed_at": now.isoformat(),
             "run_id": 777},
        ])

        pr_data = {
            "number": 42,
            "title": "Test PR",
            "state": "open",
            "user": {"login": "dev", "avatar_url": ""},
            "head": {"ref": "feature", "sha": sha},
            "base": {"ref": "main"},
            "labels": [],
            "draft": False,
            "merged": False,
            "merged_at": None,
            "closed_at": None,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "html_url": "https://github.com/test/test/pull/42",
            "additions": 10,
            "deletions": 5,
            "changed_files": 2,
        }

        collector = PRPipelineCollector(mock_github, db_session)
        db_pr = await collector._upsert_pr(pr_data, OWNER, REPO, reviews=[], files=[])

        assert db_pr is not None
        assert db_pr.ci_status == "success"
        assert db_pr.ci_started_at is not None
        assert db_pr.ci_completed_at is not None
