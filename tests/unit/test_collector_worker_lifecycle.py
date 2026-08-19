"""Regression tests for Collector task lifecycle finalization."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from collector.worker import CollectorWorker, TaskContext


def _context() -> TaskContext:
    return TaskContext(task_id=42, lease_token="lease-token", lease_generation=1)


@pytest.mark.asyncio
async def test_executor_success_marks_task_completed() -> None:
    executor = AsyncMock()
    worker = CollectorWorker(
        node_id="collector-test",
        capabilities=["python"],
        db_session_factory=None,
        task_executor=executor,
    )
    worker._complete_task = AsyncMock(return_value=True)

    assert worker.capabilities == ["python", "node:collector-test"]

    await worker._run_task_with_lease(_context())

    executor.assert_awaited_once()
    worker._complete_task.assert_awaited_once_with(42, "lease-token")


@pytest.mark.asyncio
async def test_executor_failure_requeues_task_and_preserves_exception() -> None:
    executor = AsyncMock(side_effect=RuntimeError("collector unavailable"))
    worker = CollectorWorker(
        node_id="collector-test",
        capabilities=["python"],
        db_session_factory=None,
        task_executor=executor,
    )
    worker._fail_task = AsyncMock()

    with pytest.raises(RuntimeError, match="collector unavailable"):
        await worker._run_task_with_lease(_context())

    worker._fail_task.assert_awaited_once_with(
        42,
        "lease-token",
        "collector unavailable",
        retry=True,
    )


@pytest.mark.asyncio
async def test_executor_cancellation_releases_lease_without_failure() -> None:
    executor = AsyncMock(side_effect=asyncio.CancelledError())
    worker = CollectorWorker(
        node_id="collector-test",
        capabilities=["python"],
        db_session_factory=None,
        task_executor=executor,
    )
    worker._release_task_lease = AsyncMock()

    with pytest.raises(asyncio.CancelledError):
        await worker._run_task_with_lease(_context())

    worker._release_task_lease.assert_awaited_once()
