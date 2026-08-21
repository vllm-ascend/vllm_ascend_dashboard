"""Apply the least-privilege grants required by split production services.

The Collector owns CI ingestion and its derived failure records.  Filtering a
previously persisted ``/nightly pr`` run therefore requires deleting only that
run from four Collector-owned tables.  Keep these grants table-scoped so the
service still cannot delete arbitrary application data or execute DDL.
"""

from __future__ import annotations

import logging
import os
import re

from sqlalchemy import text

from infrastructure.db.base import SessionLocal, engine

logger = logging.getLogger("service_permission_migration")

MIGRATION_VERSION = "20260821_01_collector_pr_nightly_purge"
COLLECTOR_DELETE_TABLES = (
    "ci_results",
    "ci_jobs",
    "job_failure_analysis",
    "daily_failure_records",
)
_MYSQL_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")


def _validated_identifier(value: str, *, label: str) -> str:
    if not _MYSQL_IDENTIFIER.fullmatch(value):
        raise RuntimeError(f"Invalid MySQL {label}: {value!r}")
    return value


async def run() -> dict[str, object]:
    """Grant and verify the Collector's table-scoped purge permissions."""
    if engine.dialect.name != "mysql":
        raise RuntimeError(
            f"Service permission migration requires MySQL, got {engine.dialect.name}"
        )

    collector_user = _validated_identifier(
        os.getenv("COLLECTOR_DB_USER", "collector_svc"),
        label="collector user",
    )

    async with SessionLocal() as db:
        database_name = _validated_identifier(
            str((await db.execute(text("SELECT DATABASE()"))).scalar_one()),
            label="database name",
        )
        account_exists = int(
            (
                await db.execute(
                    text(
                        "SELECT COUNT(*) FROM mysql.user "
                        "WHERE user = :user AND host = '%'"
                    ),
                    {"user": collector_user},
                )
            ).scalar_one()
        )
        if not account_exists:
            message = f"MySQL Collector account {collector_user!r}@'%' does not exist"
            if os.getenv("ENVIRONMENT", "").lower() == "production":
                raise RuntimeError(message)
            logger.warning("%s; skipping grants outside production", message)
            return {"applied": False, "tables": []}

        for table_name in COLLECTOR_DELETE_TABLES:
            table = _validated_identifier(table_name, label="table name")
            await db.execute(
                text(
                    f"GRANT DELETE ON `{database_name}`.`{table}` "
                    f"TO '{collector_user}'@'%'"
                )
            )

        await db.execute(
            text(
                "INSERT INTO schema_migrations (version, description) "
                "VALUES (:version, :description) "
                "ON DUPLICATE KEY UPDATE description = VALUES(description)"
            ),
            {
                "version": MIGRATION_VERSION,
                "description": (
                    "Grant Collector table-scoped DELETE permissions for "
                    "/nightly pr cleanup"
                ),
            },
        )
        await db.commit()

        grantee = f"'{collector_user}'@'%'"
        granted = set(
            (
                await db.execute(
                    text(
                        "SELECT table_name FROM information_schema.table_privileges "
                        "WHERE table_schema = :database_name "
                        "AND grantee = :grantee AND privilege_type = 'DELETE'"
                    ),
                    {"database_name": database_name, "grantee": grantee},
                )
            ).scalars()
        )
        missing = set(COLLECTOR_DELETE_TABLES) - granted
        if missing:
            raise RuntimeError(
                "Collector DELETE grant verification failed; missing: "
                f"{sorted(missing)}"
            )

    logger.info(
        "Migration %s complete; collector=%s tables=%s",
        MIGRATION_VERSION,
        collector_user,
        ",".join(COLLECTOR_DELETE_TABLES),
    )
    return {"applied": True, "tables": list(COLLECTOR_DELETE_TABLES)}
