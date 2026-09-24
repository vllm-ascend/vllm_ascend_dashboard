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
