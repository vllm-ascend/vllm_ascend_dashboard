import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import mysql

from api.v1.ci import (
    _build_log_root_cause_context,
    _extract_log_error_summary,
    _extract_merged_pr_number,
    _extract_revert_target,
    _fetch_pr_details_bounded,
    _merged_within_commit_boundary,
    get_ci_stats,
    list_runs,
)
from contracts.schemas import CIStats


@pytest.mark.asyncio
async def test_pr_detail_fetch_uses_bounded_concurrency_and_preserves_order():
    class FakeClient:
        def __init__(self):
            self.active = 0
            self.peak = 0

        async def get_pr_detail(self, owner, repo, number):
            self.active += 1
            self.peak = max(self.peak, self.active)
            await asyncio.sleep(0.01)
            self.active -= 1
            return {"number": number, "merged_at": "2026-09-17T00:00:00Z"}

    client = FakeClient()
    results = await _fetch_pr_details_bounded(
        client, "owner", "repo", list(range(1, 10)), max_concurrency=4
    )

    assert client.peak == 4
    assert [number for number, _, _ in results] == list(range(1, 10))
    assert all(error is None for _, _, error in results)


def test_pr_merge_time_is_constrained_by_version_commit_boundary():
    start = "2026-09-11T17:34:55+08:00"
    end = "2026-09-14T21:26:49+08:00"

    assert not _merged_within_commit_boundary("2026-09-08T09:59:00Z", start, end)
    assert _merged_within_commit_boundary("2026-09-12T02:00:00Z", start, end)
    assert not _merged_within_commit_boundary("2026-09-15T02:00:00Z", start, end)


def test_pr_merge_time_uses_available_single_sided_boundary():
    assert not _merged_within_commit_boundary(
        "2026-09-08T09:59:00Z", "2026-09-11T17:34:55+08:00", None
    )
    assert _merged_within_commit_boundary(
        "2026-09-12T09:59:00Z", "2026-09-11T17:34:55+08:00", None
    )


def test_revert_title_uses_final_number_as_current_pr():
    title = '[Revert] Revert "Feature" (#15908) (#16409)'
    assert _extract_merged_pr_number(title) == 16409


def test_revert_target_supports_generated_revert_pr_message():
    message = (
        '[Revert] Revert "Feature" (#15908) (#16409)\n\n'
        'Revert of PR #15908 (merged onto `main`).\n'
        'Original PR: #15908\n'
        'Merge commit: `daa644121e1142821777e3ba60a49ab6dd354920`'
    )
    target_pr, target_sha = _extract_revert_target(
        message,
        16409,
        {"daa644121e1142821777e3ba60a49ab6dd354920": 15908},
    )
    assert target_pr == 15908
    assert target_sha == "daa644121e1142821777e3ba60a49ab6dd354920"


def test_log_context_preserves_aisbench_verdict_over_generic_noise():
    noise = "\n".join(f"[ERROR] generic orchestration error {index}" for index in range(40))
    performance = (
        "[2026-09-10 22:26:09] [ERROR] The following aisbench case failed: "
        "{'case_type': 'performance', 'case_name': 'perf'}, reason is Performance "
        "verification failed. The current Output Token Throughput is 186.3474 token/s, "
        "which is not greater than or equal to 0.97 * baseline 347.4475."
    )
    accuracy = (
        "Accuracy verification failed. The accuracy of /datasets/aime2025 is 0.0, "
        "which is not within 10 relative to baseline 93.33."
    )

    excerpt = _build_log_root_cause_context(
        "Waiting for all pods to become Running and Ready\nStream logs\n"
        + noise + "\n" + performance + "\n" + accuracy,
        max_chars=1800,
    )

    assert "aisbench 验收失败判定" in excerpt
    assert "Output Token Throughput is 186.3474" in excerpt
    assert "accuracy of /datasets/aime2025 is 0.0" in excerpt


def test_compact_error_prefers_aisbench_verdict_to_generic_exception():
    log = (
        "AssertionError: wrapper failed\n"
        "[ERROR] The following aisbench case failed, reason is Performance verification failed. "
        "The current Output Token Throughput is 186.3474 token/s.\n"
        "RuntimeError: command failed\n"
    )

    assert "Performance verification failed" in (_extract_log_error_summary(log) or "")


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _OneResult:
    def __init__(self, row):
        self._row = row

    def one(self):
        return self._row


class _ScalarsResult:
    def scalars(self):
        return self

    def all(self):
        return []


@pytest.mark.asyncio
async def test_ci_runs_filter_and_order_by_workflow_start_time():
    db = AsyncMock()
    db.execute.side_effect = [
        _RowsResult([("nightly", None, None)]),
        _ScalarsResult(),
    ]

    await list_runs(
        db,
        start_time=datetime(2026, 9, 1, tzinfo=UTC),
        end_time=datetime(2026, 9, 7, tzinfo=UTC),
        limit=100,
    )

    statement = db.execute.await_args_list[1].args[0]
    sql = str(statement.compile(
        dialect=mysql.dialect(),
        compile_kwargs={"literal_binds": True},
    ))
    assert "ci_results.started_at >=" in sql
    assert "ci_results.started_at <=" in sql
    assert "ORDER BY ci_results.started_at DESC" in sql
    assert "coalesce(ci_results.completed_at, ci_results.started_at)" not in sql


@pytest.mark.asyncio
async def test_ci_stats_combines_workflow_and_hardware_filters_for_all_aggregates():
    db = AsyncMock()
    db.execute.side_effect = [
        _RowsResult([("nightly", None, None)]),
        _OneResult(SimpleNamespace(
            total_runs=4,
            passed_runs=1,
            failed_runs=1,
            avg_duration=90,
        )),
        _OneResult(SimpleNamespace(runs=2, success_runs=1, avg_duration=60)),
    ]

    result = await get_ci_stats(
        db,
        workflow_name="nightly",
        hardware="A2",
        start_time=datetime(2026, 9, 1, tzinfo=UTC),
        end_time=datetime(2026, 9, 7, tzinfo=UTC),
    )

    assert result["total_runs"] == 4
    assert result["passed_runs"] == 1
    assert result["failed_runs"] == 1
    assert result["other_runs"] == 2
    assert result["success_rate"] == 25.0
    assert result["last_7_days"]["success_rate"] == 50.0

    aggregate_statements = [call.args[0] for call in db.execute.await_args_list[1:]]
    for statement in aggregate_statements:
        sql = str(statement.compile(
            dialect=mysql.dialect(),
            compile_kwargs={"literal_binds": True},
        ))
        assert "ci_results.workflow_name = 'nightly'" in sql
        assert "ci_results.hardware = 'A2'" in sql
        assert "ci_results.started_at >=" in sql
        assert "ci_results.started_at <=" in sql
        assert "coalesce(ci_results.completed_at, ci_results.started_at)" not in sql


@pytest.mark.asyncio
async def test_ci_stats_returns_all_count_fields_when_no_workflows_are_enabled():
    db = AsyncMock()
    db.execute.return_value = _RowsResult([])

    result = await get_ci_stats(db)

    assert result["total_runs"] == 0
    assert result["passed_runs"] == 0
    assert result["failed_runs"] == 0
    assert result["other_runs"] == 0


def test_ci_stats_contract_keeps_existing_fields_and_adds_build_counts():
    stats = CIStats.model_validate({
        "total_runs": 3,
        "passed_runs": 1,
        "failed_runs": 1,
        "other_runs": 1,
        "success_rate": 33.33,
        "avg_duration_seconds": None,
        "last_7_days": {"runs": 0, "success_rate": 0.0, "avg_duration_seconds": None},
    })

    assert stats.model_dump() == {
        "total_runs": 3,
        "passed_runs": 1,
        "failed_runs": 1,
        "other_runs": 1,
        "success_rate": 33.33,
        "avg_duration_seconds": None,
        "last_7_days": {"runs": 0, "success_rate": 0.0, "avg_duration_seconds": None},
    }
