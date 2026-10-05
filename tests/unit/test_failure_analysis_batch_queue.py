from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from failure_analysis.failure_analysis import FailureAnalysisService


class _Rows:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return self.values


@pytest.mark.asyncio
async def test_batch_analysis_only_queues_unanalysed_jobs(monkeypatch):
    db = AsyncMock()
    db.execute.side_effect = [
        _Rows([SimpleNamespace(job_id=101), SimpleNamespace(job_id=102)]),
        _Rows([102]),
    ]
    create_task = AsyncMock(return_value=501)
    monkeypatch.setattr(
        "infrastructure.tasks.task_manager.TaskManager.create_task", create_task
    )
    direct_analysis = AsyncMock()
    service = FailureAnalysisService()
    monkeypatch.setattr(service, "analyze_failed_job", direct_analysis)

    queued = await service.analyze_batch(days_back=7, db=db)

    assert queued == [101]
    assert create_task.await_count == 1
    assert create_task.await_args.args[2] == {"job_id": 101, "triggered_by": "manual"}
    direct_analysis.assert_not_awaited()
    db.commit.assert_awaited_once()
