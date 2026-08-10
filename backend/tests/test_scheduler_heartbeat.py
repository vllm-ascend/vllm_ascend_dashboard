"""Scheduler heartbeat → /system/config/status cross-process reporting.

Phase A 拆分后 scheduler 运行在独立容器，API 进程内的 APScheduler 为空，
`/status` 必须从 scheduler_heartbeat 表判断调度器存活，而非进程内状态。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest


# --- fake async session -----------------------------------------------------

class FakeHeartbeatRow:
    """模拟 scheduler_heartbeat 单例行。"""

    def __init__(self, *, running: bool, jobs: dict, updated_at: datetime, pid: int = 1):
        self.id = 1
        self.running = running
        self.jobs = jobs
        self.updated_at = updated_at
        self.pid = pid


class FakeSession:
    """最小化异步 session：返回预设的心跳行 / last_sync；记录被 add 的新行。"""

    def __init__(self, *, heartbeat=None, last_sync=None):
        self._hb = heartbeat
        self._last_sync = last_sync
        self.added = []

    async def get(self, model, pk):
        from app.models import SchedulerHeartbeat
        if model is SchedulerHeartbeat:
            return self._hb
        return None

    async def execute(self, stmt):
        result = MagicMock()
        result.scalar = MagicMock(return_value=self._last_sync)
        return result

    def add(self, obj):
        # SQLAlchemy AsyncSession.add 是同步的（不入 await），fake 需保持一致
        self.added.append(obj)

    async def commit(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _fake_scheduler(*, running: bool, jobs: dict | None = None) -> MagicMock:
    """模拟 DataSyncScheduler：scheduler.running + get_job 返回预设 next_run_time。"""
    jobs = jobs or {}
    inner = MagicMock()
    inner.running = running

    def get_job(jid):
        if jid in jobs:
            j = MagicMock()
            j.name = jid
            j.next_run_time = jobs[jid]
            return j
        return None

    inner.get_job = get_job
    outer = MagicMock()
    outer.scheduler = inner
    return outer


_NEXT = datetime(2026, 8, 10, 10, 31, 8, tzinfo=timezone(timedelta(hours=8)))
_FRESH_JOBS = {
    "ci_data_sync": {"name": "CI Data Sync", "next_run": _NEXT.isoformat()},
    "model_report_sync": {"name": "Model Report Sync", "next_run": None},
    "project_dashboard_cache_update": {"name": "Cache Update", "next_run": None},
    "daily_summary_task": {"name": "Daily Summary", "next_run": None},
}


# --- /status endpoint behavior ----------------------------------------------

@pytest.mark.asyncio
async def test_status_fresh_heartbeat_reports_running(monkeypatch):
    """心跳新鲜且 running=True → /status 返回 running=True，next_sync 取自心跳。

    即使 API 进程内 APScheduler 未启动（prod 实况），也应报告调度器在运行。
    """
    import app.db.base as db_base
    from app.api.v1 import system_config
    from app.services import scheduler as sched_mod

    hb = FakeHeartbeatRow(running=True, jobs=_FRESH_JOBS, updated_at=datetime.now(UTC))
    session = FakeSession(heartbeat=hb, last_sync=datetime.now(UTC))
    monkeypatch.setattr(db_base, "SessionLocal", lambda: session)
    # 进程内 scheduler 为空（running=False），模拟 prod 的 API 进程
    monkeypatch.setattr(sched_mod, "get_scheduler", lambda: _fake_scheduler(running=False))

    result = await system_config.get_system_status(current_user=None)

    assert result["scheduler"]["running"] is True
    assert result["scheduler"]["tasks"]["ci_sync"]["next_sync"] == _NEXT.isoformat()
    # model_report_sync 心跳中 next_run=None
    assert result["scheduler"]["tasks"]["model_report_sync"]["next_sync"] is None


@pytest.mark.asyncio
async def test_status_stale_heartbeat_reports_not_running(monkeypatch):
    """心跳过期（>90s 未刷新）→ /status 返回 running=False，所有 next_sync 为 None。"""
    import app.db.base as db_base
    from app.api.v1 import system_config
    from app.services import scheduler as sched_mod

    stale = FakeHeartbeatRow(
        running=True,  # 即使旧值是 True，过期后也应判为未运行
        jobs=_FRESH_JOBS,
        updated_at=datetime.now(UTC) - timedelta(seconds=120),
    )
    session = FakeSession(heartbeat=stale)
    monkeypatch.setattr(db_base, "SessionLocal", lambda: session)
    monkeypatch.setattr(sched_mod, "get_scheduler", lambda: _fake_scheduler(running=False))

    result = await system_config.get_system_status(current_user=None)

    assert result["scheduler"]["running"] is False
    assert result["scheduler"]["tasks"]["ci_sync"]["next_sync"] is None
    assert result["scheduler"]["tasks"]["daily_summary"]["next_sync"] is None


@pytest.mark.asyncio
async def test_status_no_heartbeat_falls_back_to_in_process(monkeypatch):
    """无心跳行（嵌入式模式或表未建）→ 回退到进程内 APScheduler 状态。"""
    import app.db.base as db_base
    from app.api.v1 import system_config
    from app.services import scheduler as sched_mod

    session = FakeSession(heartbeat=None)  # 无心跳行
    monkeypatch.setattr(db_base, "SessionLocal", lambda: session)
    # 进程内 scheduler 在运行（嵌入式/dev 模式）
    monkeypatch.setattr(
        sched_mod, "get_scheduler",
        lambda: _fake_scheduler(running=True, jobs={"ci_data_sync": _NEXT}),
    )

    result = await system_config.get_system_status(current_user=None)

    assert result["scheduler"]["running"] is True
    assert result["scheduler"]["tasks"]["ci_sync"]["next_sync"] == _NEXT.isoformat()


# --- write_heartbeat serialization ------------------------------------------

@pytest.mark.asyncio
async def test_write_heartbeat_serializes_running_and_jobs(monkeypatch):
    """write_heartbeat 把 scheduler.running + 各 job next_run_time 写入心跳行。"""
    from app.models import SchedulerHeartbeat
    from app.services import scheduler as sched_mod
    from app.services.scheduler import DataSyncScheduler

    session = FakeSession(heartbeat=None)  # 首次写入 → db.add
    # write_heartbeat 用的是 scheduler.py 顶部 import 的 SessionLocal（模块级绑定），
    # 必须直接 patch scheduler 模块的这个名字，patch app.db.base 不生效。
    monkeypatch.setattr(sched_mod, "SessionLocal", lambda: session)

    ds = DataSyncScheduler()
    # write_heartbeat 直接用 self.scheduler（APScheduler 实例），故赋 inner 而非 outer
    ds.scheduler = _fake_scheduler(
        running=True,
        jobs={
            "ci_data_sync": _NEXT,
            "model_report_sync": None,
            "project_dashboard_cache_update": None,
            "daily_summary_task": None,
        },
    ).scheduler

    await ds.write_heartbeat()

    assert len(session.added) == 1
    row: SchedulerHeartbeat = session.added[0]
    assert row.id == 1
    assert row.running is True
    assert row.jobs["ci_data_sync"]["next_run"] == _NEXT.isoformat()
    assert row.jobs["model_report_sync"]["next_run"] is None
    assert row.pid == __import__("os").getpid()


@pytest.mark.asyncio
async def test_write_heartbeat_force_running_false_on_shutdown(monkeypatch):
    """关闭时 force_running=False → 即使 scheduler 仍在运行，心跳也写 False。"""
    from app.services import scheduler as sched_mod
    from app.services.scheduler import DataSyncScheduler

    session = FakeSession(heartbeat=None)
    monkeypatch.setattr(sched_mod, "SessionLocal", lambda: session)

    ds = DataSyncScheduler()
    ds.scheduler = _fake_scheduler(running=True, jobs={}).scheduler

    await ds.write_heartbeat(force_running=False)

    assert session.added[0].running is False
