"""
Database upgrade script v0.0.14

Add job_failure_analysis table for CI failure job intelligent diagnosis.
"""
import asyncio
import logging

from sqlalchemy import inspect, text

from app.db.base import SessionLocal, engine

logger = logging.getLogger(__name__)

DESCRIPTION = "Add job_failure_analysis table for CI failure job intelligent diagnosis"


async def check_table_exists(table_name: str) -> bool:
    try:
        def _get_table_names(conn):
            inspector = inspect(conn)
            return inspector.get_table_names()

        async with engine.begin() as conn:
            table_names = await conn.run_sync(_get_table_names)
            return table_name in table_names
    except Exception:
        return False


async def upgrade():
    print("\n" + "=" * 60)
    print("  Starting upgrade to v0.0.14")
    print("=" * 60 + "\n")

    table_name = "job_failure_analysis"
    if await check_table_exists(table_name):
        print(f"  [OK] Table {table_name} already exists")
        return

    is_mysql = "mysql" in str(engine.url)
    if is_mysql:
        create_table_sql = """
        CREATE TABLE job_failure_analysis (
            id INTEGER PRIMARY KEY AUTO_INCREMENT,
            job_id BIGINT NOT NULL UNIQUE,
            run_id BIGINT NOT NULL,
            workflow_name VARCHAR(100) NOT NULL,
            job_name VARCHAR(500) NOT NULL,
            failure_date DATETIME NOT NULL,
            failure_fingerprint VARCHAR(32),
            reused_analysis_id INTEGER,
            problem_category VARCHAR(20),
            root_cause_summary VARCHAR(500),
            improvement_measures_summary VARCHAR(500),
            report_file_path VARCHAR(200),
            llm_provider VARCHAR(50),
            llm_model VARCHAR(100),
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            generation_time_seconds DOUBLE,
            analysis_status VARCHAR(20) DEFAULT 'pending',
            error_message VARCHAR(500),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE INDEX ix_fa_job_id (job_id),
            INDEX ix_fa_run_id (run_id),
            INDEX ix_fa_workflow (workflow_name),
            INDEX ix_fa_failure_date (failure_date),
            INDEX ix_fa_category (problem_category),
            INDEX ix_fa_status (analysis_status),
            INDEX ix_fa_fingerprint (failure_fingerprint)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    else:
        create_table_sql = """
        CREATE TABLE job_failure_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id BIGINT NOT NULL UNIQUE,
            run_id BIGINT NOT NULL,
            workflow_name VARCHAR(100) NOT NULL,
            job_name VARCHAR(500) NOT NULL,
            failure_date DATETIME NOT NULL,
            failure_fingerprint VARCHAR(32),
            reused_analysis_id INTEGER,
            problem_category VARCHAR(20),
            root_cause_summary VARCHAR(500),
            improvement_measures_summary VARCHAR(500),
            report_file_path VARCHAR(200),
            llm_provider VARCHAR(50),
            llm_model VARCHAR(100),
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            generation_time_seconds REAL,
            analysis_status VARCHAR(20) DEFAULT 'pending',
            error_message VARCHAR(500),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """

    async with SessionLocal() as db:
        try:
            await db.execute(text(create_table_sql))
            if not is_mysql:
                for idx_sql in [
                    "CREATE INDEX ix_fa_run_id ON job_failure_analysis(run_id)",
                    "CREATE INDEX ix_fa_workflow ON job_failure_analysis(workflow_name)",
                    "CREATE INDEX ix_fa_failure_date ON job_failure_analysis(failure_date)",
                    "CREATE INDEX ix_fa_category ON job_failure_analysis(problem_category)",
                    "CREATE INDEX ix_fa_status ON job_failure_analysis(analysis_status)",
                    "CREATE INDEX ix_fa_fingerprint ON job_failure_analysis(failure_fingerprint)",
                ]:
                    try:
                        await db.execute(text(idx_sql))
                    except Exception:
                        pass
            await db.commit()
            print("  [OK] Created table job_failure_analysis")
        except Exception as exc:
            await db.rollback()
            logger.error("Upgrade v0.0.14 failed: %s", exc, exc_info=True)
            print(f"\n  [FAIL] Upgrade failed: {exc}")
            raise

    print("\n" + "=" * 60)
    print("  [OK] Upgrade to v0.0.14 completed successfully!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
