from datetime import UTC, datetime
from types import SimpleNamespace

from collector.nightly_data import NightlyDataCollector


def _snapshot(*, report_date: str, branch: str = "main", workflow: str = "Nightly-A3", job_name: str, test_model: str):
    return SimpleNamespace(
        report_date=report_date,
        source_branch=branch,
        workflow_name=workflow,
        job_name=job_name,
        test_model=test_model,
    )


def test_match_snapshot_prefers_exact_report_date():
    old = _snapshot(
        report_date="2026-08-13",
        job_name="old-model",
        test_model="old-model.yaml",
    )
    exact = _snapshot(
        report_date="2026-08-14",
        job_name="new-model",
        test_model="new-model.yaml",
    )
    snapshot_map = {
        ("2026-08-13", "main", "Nightly-A3", old.job_name): old,
        ("2026-08-14", "main", "Nightly-A3", exact.job_name): exact,
    }

    result = NightlyDataCollector._match_snapshot(
        snapshot_map,
        {("main", "Nightly-A3"): [exact, old]},
        report_date="2026-08-14",
        source_branch="main",
        workflow_name="Nightly-A3",
        job_name="single-node (main, new-model.yaml) / new-model",
    )

    assert result is exact


def test_match_snapshot_falls_back_for_historical_job_without_exact_snapshot():
    current = _snapshot(
        report_date="2026-08-14",
        job_name="MiniMax-M3-W8A8-A3",
        test_model="MiniMax-M3-W8A8-A3.yaml",
    )

    result = NightlyDataCollector._match_snapshot(
        {
            ("2026-08-14", "main", "Nightly-A3", current.job_name): current,
        },
        {("main", "Nightly-A3"): [current]},
        report_date="2026-08-12",
        source_branch="main",
        workflow_name="Nightly-A3",
        job_name="single-node (main, MiniMax-M3-W8A8-A3.yaml) / MiniMax-M3-W8A8-A3",
    )

    assert result is current


def test_report_date_uses_job_completion_date_when_nightly_crosses_midnight():
    job = SimpleNamespace(
        started_at=datetime(2026, 8, 17, 15, 45, tzinfo=UTC),  # 23:45 Beijing
        completed_at=datetime(2026, 8, 17, 16, 10, tzinfo=UTC),  # 00:10 next day
    )

    assert NightlyDataCollector._report_date_for_job(job) == "2026-08-18"


def test_report_date_uses_workflow_completion_for_the_whole_nightly_batch():
    job = SimpleNamespace(
        started_at=datetime(2026, 8, 17, 15, 30, tzinfo=UTC),  # 23:30 Beijing
        completed_at=datetime(2026, 8, 17, 15, 50, tzinfo=UTC),  # 23:50 Beijing
    )
    workflow_completed_at = datetime(2026, 8, 17, 16, 10, tzinfo=UTC)  # next day

    assert (
        NightlyDataCollector._report_date_for_job(job, workflow_completed_at)
        == "2026-08-18"
    )


def test_report_date_uses_workflow_completion_when_job_completion_is_missing():
    job = SimpleNamespace(
        started_at=datetime(2026, 8, 17, 15, 45, tzinfo=UTC),
        completed_at=None,
    )
    workflow_completed_at = datetime(2026, 8, 17, 16, 5, tzinfo=UTC)

    assert (
        NightlyDataCollector._report_date_for_job(job, workflow_completed_at)
        == "2026-08-18"
    )


def test_report_date_treats_naive_database_timestamps_as_utc():
    job = SimpleNamespace(
        started_at=datetime(2026, 8, 17, 15, 45),
        completed_at=datetime(2026, 8, 17, 16, 10),
    )

    assert NightlyDataCollector._report_date_for_job(job) == "2026-08-18"
