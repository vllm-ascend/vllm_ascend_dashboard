"""Opt-in, rollback-only CI flow check against the local dev MySQL (port 3310)."""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from database.migrations.task_queue import COLLECTION_TASKS_DDL
from dotenv import dotenv_values
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from api.v1.ci import list_daily_failures, list_jobs_by_run
from collector.ci import CICollector
from collector.executor import CollectorRunner
from collector.nightly_data import NightlyDataCollector
from contracts.schemas import CIResultResponse
from failure_analysis.failure_analysis import FailureAnalysisService
from infrastructure.core.config import settings
from infrastructure.persistence.models import (
    Base,
    CIJob,
    CIResult,
    DailyFailureRecord,
    JobFailureAnalysis,
    NightlyTestCase,
    WorkflowConfig,
)


def _local_engine():
    local_env = dotenv_values(Path(__file__).resolve().parents[2] / ".env.local")
    assert int(local_env["DEV_MYSQL_PORT"]) == 3310
    url = make_url(settings.DATABASE_URL).set(
        host="127.0.0.1", port=3310,
        username=local_env["MYSQL_USER"], password=local_env["MYSQL_PASSWORD"],
        database=local_env["MYSQL_DATABASE"],
    )
    assert url.database == "vllm_dashboard"
    return create_async_engine(url, pool_pre_ping=True)


def _local_root_url():
    local_env = dotenv_values(Path(__file__).resolve().parents[2] / ".env.local")
    assert int(local_env["DEV_MYSQL_PORT"]) == 3310
    return make_url(settings.DATABASE_URL).set(
        host="127.0.0.1", port=3310, username="root",
        password=local_env["MYSQL_ROOT_PASSWORD"], database="mysql",
    )


@pytest.mark.asyncio
async def test_local_dev_database_is_the_expected_target():
    if os.getenv("RUN_LOCAL_MYSQL_E2E") != "1":
        pytest.skip("Set RUN_LOCAL_MYSQL_E2E=1 to test the local development database")

    engine = _local_engine()
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(
                "SELECT DATABASE(), "
                "(SELECT COUNT(*) FROM workflow_configs), "
                "(SELECT COUNT(*) FROM nightly_test_cases)"
            ))
            database, workflows, cases = result.one()
            assert database == "vllm_dashboard"
            assert workflows > 0
            assert cases > 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_regex_to_materialization_to_analysis_queue_to_api(monkeypatch):
    if os.getenv("RUN_LOCAL_MYSQL_E2E") != "1":
        pytest.skip("Set RUN_LOCAL_MYSQL_E2E=1 to test the local development database")

    schema = f"e2e_ci_flow_{uuid.uuid4().hex[:16]}"
    assert schema.startswith("e2e_ci_flow_") and len(schema) < 64
    root_engine = create_async_engine(_local_root_url(), pool_pre_ping=True)
    async with root_engine.begin() as root_conn:
        assert (await root_conn.scalar(text("SELECT DATABASE()"))) == "mysql"
        await root_conn.execute(text(f"CREATE DATABASE `{schema}` CHARACTER SET utf8mb4"))

    engine = create_async_engine(_local_root_url().set(database=schema), pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=[
                    WorkflowConfig.__table__, NightlyTestCase.__table__,
                    CIResult.__table__, CIJob.__table__,
                    DailyFailureRecord.__table__, JobFailureAnalysis.__table__,
                ],
            ))
            await conn.execute(text(COLLECTION_TASKS_DDL))

        # Session commits release savepoints, never the outer transaction.
        async with engine.connect() as conn:
            outer = await conn.begin()
            session = AsyncSession(
                bind=conn, expire_on_commit=False, autoflush=False,
                join_transaction_mode="create_savepoint",
            )
            config = WorkflowConfig(
                workflow_name="Nightly-A3", workflow_file="nightly-a3.yml",
                hardware="A3", event="schedule", enabled=True,
                auto_failure_analysis_enabled=True,
                materialize_name_regex=r"^Nightly-A3 [(]scheduled[)]$",
                stats_start_hour=(datetime.now(timezone(timedelta(hours=8))).hour - 1) % 24,
                stats_end_hour=(datetime.now(timezone(timedelta(hours=8))).hour + 1) % 24,
            )
            session.add(config)
            await session.flush()
            suffix = uuid.uuid4().hex[:12]
            branch = f"e2e-ci-{suffix}"
            case_name = f"e2e-case-{suffix}"
            run_id = 9_000_000_000_000_000 + uuid.uuid4().int % 100_000_000
            rejected_run_id = run_id + 1
            job_id = run_id + 2
            out_of_window_run_id = run_id + 3
            now = datetime.now(UTC).replace(microsecond=0)
            today = now.astimezone(timezone(timedelta(hours=8))).date()

            session.add(NightlyTestCase(
                report_date=today, source_branch=branch,
                workflow_name=config.workflow_name, job_name=case_name,
                display_name=case_name, test_model=case_name, enabled=True,
            ))
            await session.flush()

            def run(run_id_value: int, name: str, created_at: datetime = now) -> dict:
                return {
                    "id": run_id_value, "name": name, "event": "schedule",
                    "status": "completed", "conclusion": "failure",
                    "head_branch": branch, "run_attempt": 1,
                    "created_at": created_at.isoformat(),
                    "updated_at": created_at.isoformat(),
                }

            github = SimpleNamespace(
                owner="vllm-project", repo="vllm-ascend",
                get_workflow_runs=AsyncMock(return_value=[
                    run(rejected_run_id, "Nightly-A3 (manual)"),
                    run(out_of_window_run_id, "Nightly-A3 (scheduled)", now - timedelta(hours=6)),
                    run(run_id, "Nightly-A3 (scheduled)"),
                ]),
                get_job_list=AsyncMock(return_value=[{
                    "id": job_id, "name": case_name,
                    "workflow_name": "Nightly-A3 (scheduled)",
                    "status": "completed", "conclusion": "failure",
                    "started_at": (now - timedelta(minutes=1)).isoformat(),
                    "completed_at": now.isoformat(),
                    "run_attempt": 1, "steps": [], "labels": [],
                }]),
            )
            collector = CICollector(github, session)
            collector._materialize_failure_run_artifacts = AsyncMock()  # type: ignore[method-assign]
            collector._collect_run_version_snapshot = AsyncMock()  # type: ignore[method-assign]

            assert await collector.collect_workflow_runs(
                workflow_files=[config.workflow_file], days_back=1,
            ) == 1
            assert await session.scalar(
                select(CIResult.id).where(CIResult.run_id == rejected_run_id)
            ) is None
            assert await session.scalar(
                select(CIResult.id).where(CIResult.run_id == out_of_window_run_id)
            ) is None
            parent = await session.scalar(select(CIResult).where(CIResult.run_id == run_id))
            job = await session.scalar(select(CIJob).where(CIJob.job_id == job_id))
            assert parent is not None and job is not None
            assert parent.workflow_name == job.workflow_name == "Nightly-A3"
            assert json.loads(parent.data)["name"] == "Nightly-A3 (scheduled)"
            assert json.loads(job.data)["workflow_name"] == "Nightly-A3 (scheduled)"

            nightly = NightlyDataCollector(session)
            await nightly.populate_daily_failure_records()
            record = await session.scalar(
                select(DailyFailureRecord).where(DailyFailureRecord.job_id == job_id)
            )
            assert record is not None
            assert record.workflow_name == "Nightly-A3"
            assert record.source_branch == branch
            assert job_id in nightly.last_materialized_job_ids

            monkeypatch.setattr(settings, "CI_AUTO_FAILURE_ANALYSIS_ENABLED", True)
            runner = CollectorRunner(SimpleNamespace())
            queue = await runner._enqueue_auto_failure_analysis(
                session, nightly.last_materialized_job_ids
            )
            assert queue["selected"] == queue["queued"] == 1
            queued_job = await session.scalar(text(
                "SELECT JSON_UNQUOTE(JSON_EXTRACT(task_params, '$.job_id')) "
                "FROM collection_tasks WHERE dedupe_key = :key"
            ), {"key": f"failure_analysis:{job_id}"})
            assert int(queued_job) == job_id

            @asynccontextmanager
            async def same_session():
                yield session

            monkeypatch.setattr("collector.executor.SessionLocal", same_session)
            monkeypatch.setattr(FailureAnalysisService, "_get_llm_config", AsyncMock(
                return_value=SimpleNamespace(
                    provider="test-stub", decrypted_api_key="not-a-real-key",
                    api_base_url="http://invalid.local", default_model="test-model",
                ),
            ))
            monkeypatch.setattr(FailureAnalysisService, "_get_agent_config", AsyncMock(
                return_value={"runtime": "claude_cli"},
            ))
            monkeypatch.setattr(FailureAnalysisService, "_get_system_prompt", AsyncMock(
                return_value="Analyze the supplied failing job",
            ))
            monkeypatch.setattr(FailureAnalysisService, "_build_job_context", AsyncMock(
                return_value="Synthetic failed job evidence",
            ))
            monkeypatch.setattr(
                "failure_analysis.failure_analysis.FailureAnalysisFileStore.save_report",
                AsyncMock(return_value=None),
            )
            monkeypatch.setattr(FailureAnalysisService, "_generate_pdf_async", AsyncMock())
            llm = AsyncMock(return_value=SimpleNamespace(
                content=json.dumps({
                    "problem_category": "环境问题",
                    "root_cause_summary": "Synthetic runner unavailable",
                    "improvement_measures_summary": "Restore the runner",
                    "full_report": "Synthetic investigation report",
                }, ensure_ascii=False),
                turns=1, duration_seconds=1, raw_json=None,
            ))
            monkeypatch.setattr("infrastructure.clients.claude_code_cli.run_with_fallback", llm)
            await runner._run_failure_analysis(
                SimpleNamespace(task_id=0),
                {"job_id": job_id, "triggered_by": "scheduler"},
            )
            llm.assert_awaited_once()
            analysis = await session.scalar(
                select(JobFailureAnalysis).where(JobFailureAnalysis.job_id == job_id)
            )
            assert analysis is not None
            assert analysis.analysis_status == "completed"
            assert analysis.triggered_by == "scheduler"
            assert analysis.workflow_name == "Nightly-A3"
            assert analysis.problem_category == "环境问题"
            await session.refresh(record)
            assert record.problem_category == "环境问题"

            run_api = CIResultResponse.model_validate(parent).model_dump()
            assert run_api["workflow_name"] == "Nightly-A3"
            assert "actual_workflow_name" not in run_api
            job_api = await list_jobs_by_run(run_id, session)
            assert len(job_api) == 1
            assert job_api[0].workflow_name == "Nightly-A3"
            assert "actual_workflow_name" not in job_api[0].model_dump()
            daily_api = await list_daily_failures(
                session, start_date=today.isoformat(), end_date=today.isoformat(),
                workflow_name="Nightly-A3", processing_status=None, notes_search=None,
            )
            daily_row = next(
                item for day in daily_api for item in day.jobs if item.job_id == job_id
            )
            assert daily_row.workflow_name == "Nightly-A3"
            assert daily_row.problem_category == "环境问题"
            await session.close()
            await outer.rollback()
    finally:
        await engine.dispose()
        async with root_engine.begin() as root_conn:
            exists = await root_conn.scalar(text(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name = :schema"
            ), {"schema": schema})
            if exists is not None:
                await root_conn.execute(text(f"DROP DATABASE `{schema}`"))
        await root_engine.dispose()
