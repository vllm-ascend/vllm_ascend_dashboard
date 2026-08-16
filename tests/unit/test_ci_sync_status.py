from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest


class _Session:
    def __init__(self, heartbeat):
        self.heartbeat = heartbeat

    async def get(self, _model, _key):
        return self.heartbeat

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


@pytest.mark.asyncio
async def test_ci_sync_status_reads_scheduler_heartbeat(monkeypatch):
    import infrastructure.db.base as db_base
    from api.v1 import ci

    heartbeat = SimpleNamespace(
        running=True,
        updated_at=datetime.now(UTC),
        jobs={
            "ci_data_sync": {"name": "CI Data Sync", "next_run": "2026-08-16T02:00:00+00:00"},
        },
    )
    monkeypatch.setattr(db_base, "SessionLocal", lambda: _Session(heartbeat))

    result = await ci.get_sync_status()

    assert result["scheduler_running"] is True
    assert result["jobs"] == [
        {
            "id": "ci_data_sync",
            "name": "CI Data Sync",
            "next_run_time": "2026-08-16T02:00:00+00:00",
        }
    ]
    assert result["error"] is None


@pytest.mark.asyncio
async def test_ci_sync_status_reports_stale_heartbeat(monkeypatch):
    from datetime import timedelta

    import infrastructure.db.base as db_base
    from api.v1 import ci

    heartbeat = SimpleNamespace(
        running=True,
        updated_at=datetime.now(UTC) - timedelta(seconds=120),
        jobs={},
    )
    monkeypatch.setattr(db_base, "SessionLocal", lambda: _Session(heartbeat))

    result = await ci.get_sync_status()

    assert result["scheduler_running"] is False
    assert result["error"] == "scheduler heartbeat unavailable"
