"""
Database upgrade script v0.0.18

Add test observability dashboard tables: test_cases, test_runs, test_suite_snapshots, failure_annotations
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.db.base import SessionLocal, engine

logger = logging.getLogger(__name__)

DESCRIPTION = "Add test observability dashboard tables (test_cases, test_runs, test_suite_snapshots, failure_annotations)"


async def check_table_exists(table_name: str) -> bool:
    try:
        async with engine.begin() as conn:
            result = await conn.run_sync(
                lambda sync_conn: sync_conn.execute(text(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table_name}'"))
            )
            return result.fetchone() is not None
    except Exception:
        return False


async def upgrade():
    print("\n" + "=" * 60)
    print("  Starting upgrade to v0.0.18")
    print("=" * 60 + "\n")

    tables = [
        ("test_cases", """
            CREATE TABLE IF NOT EXISTS test_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_name VARCHAR(500) NOT NULL,
                test_suite VARCHAR(100) NOT NULL,
                module_name VARCHAR(100),
                test_type VARCHAR(20) NOT NULL,
                hardware VARCHAR(20),
                card_count INTEGER,
                file_path VARCHAR(500),
                class_name VARCHAR(200),
                test_name_hash VARCHAR(32),
                owner VARCHAR(100),
                owner_email VARCHAR(100),
                inference_confidence FLOAT DEFAULT 0.0,
                data_granularity VARCHAR(20) DEFAULT 'file_level',
                is_flaky BOOLEAN DEFAULT 0,
                flaky_rate FLOAT DEFAULT 0.0,
                flaky_evidence_count INTEGER DEFAULT 0,
                flip_count_30d INTEGER DEFAULT 0,
                pass_rate_7d FLOAT,
                pass_rate_30d FLOAT,
                avg_duration_seconds FLOAT,
                duration_p90_seconds FLOAT,
                health_score FLOAT,
                health_level VARCHAR(1),
                first_seen_at TIMESTAMP,
                last_seen_at TIMESTAMP,
                last_result VARCHAR(20),
                last_run_at TIMESTAMP,
                total_runs INTEGER DEFAULT 0,
                total_passed INTEGER DEFAULT 0,
                total_failed INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """),
        ("test_runs", """
            CREATE TABLE IF NOT EXISTS test_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_case_id INTEGER NOT NULL REFERENCES test_cases(id),
                ci_job_id BIGINT,
                ci_run_id BIGINT,
                workflow_name VARCHAR(100),
                job_name VARCHAR(500),
                result VARCHAR(20) NOT NULL,
                duration_seconds FLOAT,
                model_load_seconds FLOAT,
                test_exec_seconds FLOAT,
                failure_category VARCHAR(30),
                failure_message VARCHAR(1000),
                flip_detected BOOLEAN DEFAULT 0,
                head_sha VARCHAR(40),
                event VARCHAR(50),
                branch VARCHAR(100),
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """),
        ("test_suite_snapshots", """
            CREATE TABLE IF NOT EXISTS test_suite_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                suite_name VARCHAR(100) NOT NULL,
                test_type VARCHAR(20) NOT NULL,
                hardware VARCHAR(20),
                card_count INTEGER,
                snapshot_date VARCHAR(10) NOT NULL,
                total_cases INTEGER DEFAULT 0,
                passed_cases INTEGER DEFAULT 0,
                failed_cases INTEGER DEFAULT 0,
                skipped_cases INTEGER DEFAULT 0,
                flaky_cases INTEGER DEFAULT 0,
                pass_rate FLOAT,
                health_score FLOAT,
                health_level VARCHAR(1),
                avg_duration_seconds FLOAT,
                duration_p50_seconds FLOAT,
                duration_p90_seconds FLOAT,
                total_duration_seconds FLOAT,
                failure_by_category JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """),
        ("failure_annotations", """
            CREATE TABLE IF NOT EXISTS failure_annotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_run_id INTEGER NOT NULL REFERENCES test_runs(id),
                annotated_category VARCHAR(30) NOT NULL,
                annotated_by VARCHAR(100) NOT NULL,
                annotation_source VARCHAR(20) DEFAULT 'manual',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """),
    ]

    indexes = [
        "CREATE INDEX IF NOT EXISTS ix_test_cases_test_suite ON test_cases(test_suite)",
        "CREATE INDEX IF NOT EXISTS ix_test_cases_module_name ON test_cases(module_name)",
        "CREATE INDEX IF NOT EXISTS ix_test_cases_test_type ON test_cases(test_type)",
        "CREATE INDEX IF NOT EXISTS ix_test_cases_hardware ON test_cases(hardware)",
        "CREATE INDEX IF NOT EXISTS ix_test_cases_test_name_hash ON test_cases(test_name_hash)",
        "CREATE INDEX IF NOT EXISTS ix_test_cases_owner ON test_cases(owner)",
        "CREATE INDEX IF NOT EXISTS ix_test_cases_is_flaky ON test_cases(is_flaky)",
        "CREATE INDEX IF NOT EXISTS ix_test_cases_health_level ON test_cases(health_level)",
        "CREATE INDEX IF NOT EXISTS ix_test_cases_last_result ON test_cases(last_result)",
        "CREATE INDEX IF NOT EXISTS ix_test_cases_last_run_at ON test_cases(last_run_at)",
        "CREATE INDEX IF NOT EXISTS ix_test_case_module ON test_cases(module_name, test_type)",
        "CREATE INDEX IF NOT EXISTS ix_test_case_health ON test_cases(health_level, is_flaky)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_test_case_identity ON test_cases(test_name, test_suite, hardware)",
        "CREATE INDEX IF NOT EXISTS ix_test_runs_test_case_id ON test_runs(test_case_id)",
        "CREATE INDEX IF NOT EXISTS ix_test_runs_ci_job_id ON test_runs(ci_job_id)",
        "CREATE INDEX IF NOT EXISTS ix_test_runs_ci_run_id ON test_runs(ci_run_id)",
        "CREATE INDEX IF NOT EXISTS ix_test_runs_workflow_name ON test_runs(workflow_name)",
        "CREATE INDEX IF NOT EXISTS ix_test_runs_result ON test_runs(result)",
        "CREATE INDEX IF NOT EXISTS ix_test_runs_failure_category ON test_runs(failure_category)",
        "CREATE INDEX IF NOT EXISTS ix_test_runs_head_sha ON test_runs(head_sha)",
        "CREATE INDEX IF NOT EXISTS ix_test_runs_event ON test_runs(event)",
        "CREATE INDEX IF NOT EXISTS ix_test_runs_started_at ON test_runs(started_at)",
        "CREATE INDEX IF NOT EXISTS ix_test_run_case_date ON test_runs(test_case_id, started_at)",
        "CREATE INDEX IF NOT EXISTS ix_test_run_result ON test_runs(result, started_at)",
        "CREATE INDEX IF NOT EXISTS ix_suite_snapshots_suite_name ON test_suite_snapshots(suite_name)",
        "CREATE INDEX IF NOT EXISTS ix_suite_snapshots_test_type ON test_suite_snapshots(test_type)",
        "CREATE INDEX IF NOT EXISTS ix_suite_snapshots_hardware ON test_suite_snapshots(hardware)",
        "CREATE INDEX IF NOT EXISTS ix_suite_snapshots_snapshot_date ON test_suite_snapshots(snapshot_date)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_suite_snapshot ON test_suite_snapshots(suite_name, hardware, card_count, snapshot_date)",
        "CREATE INDEX IF NOT EXISTS ix_failure_annotations_test_run_id ON failure_annotations(test_run_id)",
        "CREATE INDEX IF NOT EXISTS ix_failure_annotations_annotated_category ON failure_annotations(annotated_category)",
    ]

    for table_name, create_sql in tables:
        if await check_table_exists(table_name):
            print(f"  [OK] Table '{table_name}' already exists")
        else:
            async with SessionLocal() as db:
                try:
                    await db.execute(text(create_sql))
                    await db.commit()
                    print(f"  [OK] Created table '{table_name}'")
                except Exception as e:
                    await db.rollback()
                    logger.error(f"Failed to create table {table_name}: %s", e)
                    print(f"  [FAIL] Failed to create table '{table_name}': {e}")
                    raise

    async with SessionLocal() as db:
        for idx_sql in indexes:
            try:
                await db.execute(text(idx_sql))
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.warning(f"Index creation skipped (may already exist): {e}")

    print("\n  [OK] All indexes created")

    print("\n" + "=" * 60)
    print("  [OK] Upgrade to v0.0.18 completed successfully!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
