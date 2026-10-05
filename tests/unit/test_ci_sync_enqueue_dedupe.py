from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from scheduler.service import DataSyncScheduler


@pytest.mark.asyncio
async def test_scheduled_and_manual_ci_sync_share_one_active_dedupe_key(monkeypatch) -> None:
    db = SimpleNamespace(commit=AsyncMock())
    session = AsyncMock()
    session.__aenter__.return_value = db
    session.__aexit__.return_value = False
    monkeypatch.setattr("scheduler.service.SessionLocal", Mock(return_value=session))
    create_task = AsyncMock(side_effect=[101, None, 102, None])
    monkeypatch.setattr("infrastructure.tasks.task_manager.TaskManager.create_task", create_task)
    scheduler = DataSyncScheduler()

    await scheduler._sync_ci_data_job()
    await scheduler._sync_ci_data_job()
    first_manual = await scheduler.trigger_manual_sync("ci", days_back=1, max_runs_per_workflow=2)
    second_manual = await scheduler.trigger_manual_sync("ci", days_back=1, max_runs_per_workflow=2)

    assert first_manual["queued"] is True
    assert second_manual["queued"] is False
    assert {call.args[3] for call in create_task.await_args_list} == {"ci_sync:active"}
