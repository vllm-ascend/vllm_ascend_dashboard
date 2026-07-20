"""Apply idempotent production MySQL schema migrations.

This command never creates, resets, or deletes users. Run it only after a
verified database backup has been created.
"""
import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.base import SessionLocal, engine

logger = logging.getLogger("mysql_schema_migration")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

MIGRATION_VERSION = "20260720_01_mysql_schema_compatibility"
TABLE_COLUMN_MIGRATIONS = {
    "user_login_logs": {
        "ip_address_hashed": "VARCHAR(64) NULL",
        "login_method": "VARCHAR(20) NULL",
        "user_agent": "VARCHAR(500) NULL",
        "created_at": "TIMESTAMP NULL",
    },
    "job_failure_analysis": {
        "analysis_phase": "VARCHAR(30) NULL",
        "evidence_ledger": "JSON NULL",
        "validation_result": "JSON NULL",
        "agent_trace": "JSON NULL",
        "agent_steps": "INT NOT NULL DEFAULT 0",
    },
    "ci_jobs": {
        "processing_status": "VARCHAR(20) NOT NULL DEFAULT '未处理'",
        "notes": "TEXT NULL",
        "updated_by": "VARCHAR(50) NULL",
        "status_updated_at": "TIMESTAMP NULL",
    },
    "pull_requests": {
        "author_email": "VARCHAR(200) NULL",
        "author_avatar_base64": "LONGTEXT NULL",
    },
    "test_cases": {
        "lifetime_runs": "INT NOT NULL DEFAULT 0",
        "lifetime_failures": "INT NOT NULL DEFAULT 0",
        "issues_found": "INT NOT NULL DEFAULT 0",
        "suspected_test_issue_count": "INT NOT NULL DEFAULT 0",
        "is_flaky_manual": "BOOLEAN NOT NULL DEFAULT FALSE",
    },
}
INDEX_MIGRATIONS = {
    "ci_jobs": {"ix_ci_jobs_processing_status": "processing_status"},
    "test_cases": {"ix_test_cases_is_flaky_manual": "is_flaky_manual"},
}


async def _inspection(db, table: str) -> tuple[set[str], set[str]]:
    def inspect_schema(sync_session):
        inspector = inspect(sync_session.connection())
        columns = {item["name"] for item in inspector.get_columns(table)}
        indexes = {item["name"] for item in inspector.get_indexes(table)}
        return columns, indexes

    return await db.run_sync(inspect_schema)


async def migrate() -> None:
    if engine.dialect.name != "mysql":
        raise RuntimeError(f"MySQL migration refused for dialect: {engine.dialect.name}")

    async with SessionLocal() as db:
        acquired = (await db.execute(
            text("SELECT GET_LOCK('vllm_dashboard_schema_migration', 30)")
        )).scalar_one()
        if acquired != 1:
            raise RuntimeError("Could not acquire MySQL schema migration lock")

        try:
            user_count_before = int((await db.execute(text("SELECT COUNT(*) FROM users"))).scalar_one())
            added: list[str] = []
            for table, definitions in TABLE_COLUMN_MIGRATIONS.items():
                columns, indexes = await _inspection(db, table)
                for name, definition in definitions.items():
                    if name not in columns:
                        logger.info("Adding %s.%s", table, name)
                        await db.execute(text(
                            f"ALTER TABLE `{table}` ADD COLUMN `{name}` {definition}"
                        ))
                        added.append(f"{table}.{name}")
                for index_name, column_name in INDEX_MIGRATIONS.get(table, {}).items():
                    if index_name not in indexes:
                        logger.info("Creating index %s", index_name)
                        await db.execute(text(
                            f"CREATE INDEX `{index_name}` ON `{table}` (`{column_name}`)"
                        ))

            if any(item in added for item in (
                "test_cases.lifetime_runs", "test_cases.lifetime_failures"
            )):
                logger.info("Backfilling lifetime counters from retained test_runs")
                await db.execute(text("""
                    UPDATE test_cases tc
                    LEFT JOIN (
                        SELECT test_case_id,
                               COUNT(*) AS run_count,
                               SUM(CASE WHEN result = 'failed' THEN 1 ELSE 0 END) AS failure_count
                        FROM test_runs
                        GROUP BY test_case_id
                    ) totals ON totals.test_case_id = tc.id
                    SET tc.lifetime_runs = COALESCE(totals.run_count, 0),
                        tc.lifetime_failures = COALESCE(totals.failure_count, 0)
                """))

            await db.execute(text("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(100) PRIMARY KEY,
                    applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    description VARCHAR(500) NOT NULL
                ) ENGINE=InnoDB
            """))
            await db.execute(text("""
                INSERT INTO schema_migrations (version, description)
                VALUES (:version, :description)
                ON DUPLICATE KEY UPDATE description = VALUES(description)
            """), {
                "version": MIGRATION_VERSION,
                "description": "Move compatibility schema changes into an explicit MySQL migration",
            })
            await db.commit()

            user_count_after = int((await db.execute(text("SELECT COUNT(*) FROM users"))).scalar_one())
            if user_count_after != user_count_before:
                raise RuntimeError(
                    f"User count changed during migration: {user_count_before} -> {user_count_after}"
                )

            missing: list[str] = []
            for table, definitions in TABLE_COLUMN_MIGRATIONS.items():
                final_columns, final_indexes = await _inspection(db, table)
                missing.extend(
                    f"{table}.{name}" for name in set(definitions) - final_columns
                )
                missing.extend(
                    f"{table}.{name}" for name in set(INDEX_MIGRATIONS.get(table, {})) - final_indexes
                )
            if missing:
                raise RuntimeError(f"Migration verification failed; missing: {sorted(missing)}")
            logger.info(
                "Migration %s complete; users=%s; added=%s",
                MIGRATION_VERSION,
                user_count_after,
                ",".join(added) or "none",
            )
        finally:
            await db.execute(text("SELECT RELEASE_LOCK('vllm_dashboard_schema_migration')"))


async def main() -> None:
    try:
        await migrate()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
