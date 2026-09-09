"""Integration coverage for the Collector's persisted runtime status."""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

from collector.worker import CollectorWorker
from infrastructure.db.base import SessionLocal, engine


@pytest.mark.asyncio
async def test_collector_publishes_and_stops_its_heartbeat() -> None:
    from database.migrations.process_runtime import run as run_process_runtime_migration

    await run_process_runtime_migration()
    node_id = f"test-collector-{uuid.uuid4().hex}"
    worker = CollectorWorker(
        node_id=node_id,
        capabilities=["python", "network"],
        db_session_factory=SessionLocal,
    )

    await worker._write_heartbeat(running=True)
    async with SessionLocal() as db:
        row = (
            await db.execute(
                text(
                    "SELECT capabilities, running, active_tasks, pid, updated_at "
                    "FROM collector_heartbeats WHERE node_id = :node_id"
                ),
                {"node_id": node_id},
            )
        ).one()

    assert bool(row.running) is True
    assert row.active_tasks == 0
    assert row.pid is not None
    assert set(json.loads(row.capabilities)) == {"python", "network", f"node:{node_id}"}
    assert row.updated_at is not None

    await worker._write_heartbeat(running=False)
    async with SessionLocal() as db:
        running = (
            await db.execute(
                text("SELECT running FROM collector_heartbeats WHERE node_id = :node_id"),
                {"node_id": node_id},
            )
        ).scalar_one()
    assert bool(running) is False
    # The application engine is process-scoped. Dispose test connections so a
    # following test, which pytest may run in a different event loop, gets a
    # fresh aiomysql connection instead of a cross-loop future.
    await engine.dispose()
