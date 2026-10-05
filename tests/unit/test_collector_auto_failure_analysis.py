from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from collector.executor import CollectorRunner


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


@pytest.mark.asyncio
async def test_auto_failure_analysis_queues_all_failures_from_current_sync(monkeypatch):
    db = AsyncMock()
    db.execute.side_effect = [
        _Result([]),
        _Result([(101,), (102,), (103,)]),
    ]
    create_task = AsyncMock(return_value=9001)
    monkeypatch.setattr(
        "infrastructure.tasks.task_manager.TaskManager.create_task",
        create_task,
    )

    result = await CollectorRunner(SimpleNamespace())._enqueue_auto_failure_analysis(
        db,
        {101, 102, 103},
    )

    assert result == {"selected": 3, "queued": 3, "skipped": 0, "active": 0}
    assert create_task.await_count == 3
    assert [call.args[2]["job_id"] for call in create_task.await_args_list] == [101, 102, 103]
    assert all("force" not in call.args[2] for call in create_task.await_args_list)
    assert [call.args[2]["triggered_by"] for call in create_task.await_args_list] == ["scheduler", "scheduler", "scheduler"]
    candidate_sql = str(db.execute.await_args_list[1].args[0])
    assert "JOIN ci_results" in candidate_sql
    assert "ci_results.run_id = ci_jobs.run_id" in candidate_sql
    assert "ci_results.run_id = daily_failure_records.run_id" in candidate_sql
    assert "ci_results.workflow_name = ci_jobs.workflow_name" in candidate_sql
    assert "JOIN workflow_configs" in candidate_sql
    assert "workflow_configs.auto_failure_analysis_enabled IS true" in candidate_sql


@pytest.mark.asyncio
async def test_auto_failure_analysis_skips_empty_sync(monkeypatch):
    db = AsyncMock()
    create_task = AsyncMock()
    monkeypatch.setattr(
        "infrastructure.tasks.task_manager.TaskManager.create_task",
        create_task,
    )

    result = await CollectorRunner(SimpleNamespace())._enqueue_auto_failure_analysis(
        db,
        set(),
    )

    assert result == {"selected": 0, "queued": 0, "skipped": 0, "active": 0}
    create_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_failure_analysis_switch_can_be_disabled(monkeypatch):
    db = AsyncMock()
    create_task = AsyncMock()
    monkeypatch.setattr(
        "infrastructure.tasks.task_manager.TaskManager.create_task",
        create_task,
    )
    monkeypatch.setattr("collector.executor.settings.CI_AUTO_FAILURE_ANALYSIS_ENABLED", False)

    result = await CollectorRunner(SimpleNamespace())._enqueue_auto_failure_analysis(
        db,
        {101},
    )

    assert result == {"selected": 0, "queued": 0, "skipped": 0, "active": 0}
    create_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_failure_analysis_skips_jobs_with_active_tasks(monkeypatch):
    db = AsyncMock()
    db.execute.side_effect = [_Result([("101",), ("102",)]), _Result([])]
    create_task = AsyncMock()
    monkeypatch.setattr(
        "infrastructure.tasks.task_manager.TaskManager.create_task",
        create_task,
    )

    result = await CollectorRunner(SimpleNamespace())._enqueue_auto_failure_analysis(db, {103})

    assert result == {"selected": 0, "queued": 0, "skipped": 0, "active": 2}
    create_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_scheduler_analysis_rechecks_persisted_workflow_before_execution(monkeypatch):
    db = SimpleNamespace(scalar=AsyncMock(return_value=None))

    class SessionContext:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr("collector.executor.SessionLocal", SessionContext)
    analyze = AsyncMock()
    monkeypatch.setattr(
        "failure_analysis.failure_analysis.FailureAnalysisService.analyze_failed_job",
        analyze,
    )
    runner = CollectorRunner(SimpleNamespace())
    ctx = SimpleNamespace()

    await runner._run_failure_analysis(ctx, {"job_id": 123, "triggered_by": "scheduler"})
    analyze.assert_not_awaited()

    db.scalar.return_value = 123
    await runner._run_failure_analysis(ctx, {"job_id": 123, "triggered_by": "scheduler"})
    analyze.assert_awaited_once()

    db.scalar.reset_mock()
    await runner._run_failure_analysis(ctx, {"job_id": 456, "triggered_by": "manual"})
    db.scalar.assert_not_awaited()
