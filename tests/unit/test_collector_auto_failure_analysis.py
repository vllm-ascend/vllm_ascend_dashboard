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
async def test_auto_failure_analysis_queues_only_unanalysed_jobs(monkeypatch):
    db = AsyncMock()
    db.execute.side_effect = [
        _Result([(101,), (102,)]),
        _Result([(101, "completed"), (102, "failed")]),
        _Result([(101,), (102,)]),
    ]
    create_task = AsyncMock(return_value=9001)
    monkeypatch.setattr(
        "infrastructure.tasks.task_manager.TaskManager.create_task",
        create_task,
    )

    result = await CollectorRunner(SimpleNamespace())._enqueue_auto_failure_analysis(
        db,
        {101, 102},
    )

    assert result == {"selected": 2, "queued": 1, "skipped": 1}
    create_task.assert_awaited_once_with(
        db,
        "failure_analysis",
        {"job_id": 102, "force": False, "triggered_by": "scheduler"},
        "failure_analysis:102",
        required_capability="python",
        priority=20,
    )
