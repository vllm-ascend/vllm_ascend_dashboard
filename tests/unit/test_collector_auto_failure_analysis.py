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
async def test_auto_failure_analysis_respects_limit(monkeypatch):
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
        max_items=2,
    )

    assert result == {"selected": 2, "queued": 2, "skipped": 0, "limit": 2, "active": 0}
    assert create_task.await_count == 2
    assert [call.args[2]["job_id"] for call in create_task.await_args_list] == [101, 102]


@pytest.mark.asyncio
async def test_auto_failure_analysis_can_be_disabled(monkeypatch):
    db = AsyncMock()
    create_task = AsyncMock()
    monkeypatch.setattr(
        "infrastructure.tasks.task_manager.TaskManager.create_task",
        create_task,
    )

    result = await CollectorRunner(SimpleNamespace())._enqueue_auto_failure_analysis(
        db,
        {101},
        max_items=0,
    )

    assert result == {"selected": 0, "queued": 0, "skipped": 0, "limit": 0, "active": 0}
    create_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_failure_analysis_does_not_fill_active_slots(monkeypatch):
    db = AsyncMock()
    db.execute.return_value = _Result([("101",), ("102",)])
    create_task = AsyncMock()
    monkeypatch.setattr(
        "infrastructure.tasks.task_manager.TaskManager.create_task",
        create_task,
    )

    result = await CollectorRunner(SimpleNamespace())._enqueue_auto_failure_analysis(
        db,
        {103},
        max_items=2,
    )

    assert result == {"selected": 0, "queued": 0, "skipped": 0, "limit": 2, "active": 2}
    create_task.assert_not_awaited()
