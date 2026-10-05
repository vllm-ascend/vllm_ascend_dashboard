from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from collector.ci import CICollector, CIWorkflowCollectionError
from infrastructure.tasks.sync_progress import SyncProgress


@pytest.mark.asyncio
async def test_ci_sync_with_a_failed_workflow_is_not_reported_as_complete() -> None:
    config = SimpleNamespace(
        workflow_file="nightly-a3.yml",
        hardware="A3",
        event="schedule",
        actor=None,
        stats_start_hour=21,
        stats_end_hour=3,
        materialize_name_regex=r"^Nightly-A3 [(]scheduled[)]$",
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                scalars=lambda: SimpleNamespace(all=lambda: [config]),
            )
        ),
        rollback=AsyncMock(),
    )
    progress = SyncProgress()
    collector = CICollector(None, db, sync_progress=progress)  # type: ignore[arg-type]
    collector._persist_progress = AsyncMock()  # type: ignore[method-assign]
    collector._collect_single_workflow = AsyncMock(  # type: ignore[method-assign]
        side_effect=RuntimeError("database lock wait timeout")
    )

    with pytest.raises(CIWorkflowCollectionError, match="nightly-a3.yml"):
        await collector.collect_workflow_runs(days_back=7)

    assert progress.status == "failed"
    assert progress.completed_workflows == 0
    assert progress.workflow_details["nightly-a3.yml"]["status"] == "failed"
    assert progress.workflow_details["nightly-a3.yml"]["error"] == "database lock wait timeout"
    assert progress.completed_at is not None


def test_each_ci_task_can_keep_an_independent_progress_tracker() -> None:
    first = SyncProgress(total_workflows=1)
    second = SyncProgress(total_workflows=1)
    first.start()
    second.start()

    first.update_workflow_progress("a3.yml", 1, "failed", "lock timeout")

    assert first.workflow_details["a3.yml"]["status"] == "failed"
    assert second.workflow_details == {}
    assert second.status == "running"
