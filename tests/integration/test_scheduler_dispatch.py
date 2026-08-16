"""Scheduler dispatch must create durable work instead of doing GitHub I/O."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from infrastructure.db.base import SessionLocal, engine
from scheduler.service import DataSyncScheduler


@pytest.mark.asyncio
async def test_pr_schedule_enqueues_a_collector_task() -> None:
    from database.migrations.task_queue import run as run_task_queue_migration

    await run_task_queue_migration()
    scheduler = DataSyncScheduler()
    try:
        await scheduler._sync_pr_pipeline_job()
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    text(
                        "SELECT task_type, task_params, status, required_capability "
                        "FROM collection_tasks "
                        "WHERE dedupe_key LIKE 'pr_sync:scheduled:%' "
                        "ORDER BY id DESC LIMIT 1"
                    )
                )
            ).one()

        assert row.task_type == "pr_sync"
        assert row.status == "pending"
        assert row.required_capability == "python"
        params = json.loads(row.task_params) if isinstance(row.task_params, str) else row.task_params
        assert "days_back" in params
        assert params["incremental"] is True
        assert "max_items" in params
        assert "lookback_minutes" in params
    finally:
        if scheduler.scheduler.running:
            scheduler.scheduler.shutdown(wait=False)
        await engine.dispose()


@pytest.mark.asyncio
async def test_ci_schedule_enqueues_a_collector_task() -> None:
    from database.migrations.task_queue import run as run_task_queue_migration

    await run_task_queue_migration()
    scheduler = DataSyncScheduler()
    try:
        await scheduler._sync_ci_data_job()
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    text(
                        "SELECT task_type, task_params, status, required_capability "
                        "FROM collection_tasks "
                        "WHERE dedupe_key LIKE 'ci_sync:scheduled:%' "
                        "ORDER BY id DESC LIMIT 1"
                    )
                )
            ).one()

        assert row.task_type == "ci_sync"
        assert row.status == "pending"
        assert row.required_capability == "python"
        assert "days_back" in row.task_params
        assert "max_runs" in row.task_params
    finally:
        if scheduler.scheduler.running:
            scheduler.scheduler.shutdown(wait=False)
        await engine.dispose()


@pytest.mark.asyncio
async def test_model_schedule_enqueues_a_collector_task() -> None:
    from database.migrations.task_queue import run as run_task_queue_migration

    await run_task_queue_migration()
    scheduler = DataSyncScheduler()
    try:
        await scheduler._sync_model_reports_job()
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    text(
                        "SELECT task_type, task_params, status, required_capability "
                        "FROM collection_tasks "
                        "WHERE dedupe_key LIKE 'model_sync:scheduled:%' "
                        "ORDER BY id DESC LIMIT 1"
                    )
                )
            ).one()

        assert row.task_type == "model_sync"
        assert row.status == "pending"
        assert row.required_capability == "python"
        assert "days_back" in row.task_params
        assert "runs_limit" in row.task_params
    finally:
        if scheduler.scheduler.running:
            scheduler.scheduler.shutdown(wait=False)
        await engine.dispose()


@pytest.mark.asyncio
async def test_code_metrics_schedule_enqueues_a_collector_task() -> None:
    from database.migrations.task_queue import run as run_task_queue_migration

    await run_task_queue_migration()
    scheduler = DataSyncScheduler()
    try:
        await scheduler._collect_code_metrics_job()
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    text(
                        "SELECT task_type, task_params, status, required_capability "
                        "FROM collection_tasks "
                        "WHERE dedupe_key LIKE 'code_metrics:scheduled:%' "
                        "ORDER BY id DESC LIMIT 1"
                    )
                )
            ).one()

        assert row.task_type == "code_metrics_collect"
        assert row.status == "pending"
        assert row.required_capability == "python"
        assert "main" in row.task_params
    finally:
        if scheduler.scheduler.running:
            scheduler.scheduler.shutdown(wait=False)
        await engine.dispose()


@pytest.mark.asyncio
async def test_heatmap_schedule_enqueues_a_collector_task() -> None:
    from database.migrations.task_queue import run as run_task_queue_migration

    await run_task_queue_migration()
    scheduler = DataSyncScheduler()
    try:
        await scheduler._sync_heatmap_job()
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    text(
                        "SELECT task_type, task_params, status, required_capability "
                        "FROM collection_tasks "
                        "WHERE dedupe_key LIKE 'code_heatmap_sync:scheduled:%' "
                        "ORDER BY id DESC LIMIT 1"
                    )
                )
            ).one()

        assert row.task_type == "code_heatmap_sync"
        assert row.status == "pending"
        assert row.required_capability == "python"
        assert "days" in row.task_params
    finally:
        if scheduler.scheduler.running:
            scheduler.scheduler.shutdown(wait=False)
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("job_name", "task_type"),
    [
        ("_collect_resource_metrics_job", "resource_metrics_collect"),
        ("_cleanup_resource_metrics_job", "resource_metrics_cleanup"),
    ],
)
async def test_resource_metric_schedule_enqueues_collector_work(job_name: str, task_type: str) -> None:
    from database.migrations.task_queue import run as run_task_queue_migration

    await run_task_queue_migration()
    scheduler = DataSyncScheduler()
    try:
        await getattr(scheduler, job_name)()
        async with SessionLocal() as db:
            row = (
                await db.execute(
                    text(
                        "SELECT task_type, status, required_capability FROM collection_tasks "
                        "WHERE task_type = :task_type ORDER BY id DESC LIMIT 1"
                    ),
                    {"task_type": task_type},
                )
            ).one()
        assert row.task_type == task_type
        assert row.status == "pending"
        assert row.required_capability == "python"
    finally:
        if scheduler.scheduler.running:
            scheduler.scheduler.shutdown(wait=False)
        await engine.dispose()
