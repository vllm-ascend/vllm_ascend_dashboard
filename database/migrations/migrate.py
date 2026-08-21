"""Canonical database migration command for the dashboard.

This command is safe to repeat: it creates missing current-schema tables and
then applies the explicit MySQL compatibility and task-queue migrations. It
never creates, resets, or deletes application users.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import text

repository_root = Path(__file__).resolve().parents[2]
# Source checkouts keep application code under ``backend/``; the production
# image copies it directly to ``/app``. Database code keeps the same package
# path in both layouts so the migration entrypoint is deterministic.
application_root = repository_root / "backend"
if not application_root.is_dir():
    application_root = repository_root
sys.path.insert(0, str(application_root))

from database.bootstrap import create_tables_with_latest_schema
from database.migrations.mysql_schema import migrate as migrate_mysql_schema
from database.migrations.process_runtime import run as migrate_process_runtime
from database.migrations.service_permissions import run as migrate_service_permissions
from database.migrations.task_queue import run as migrate_phase_a
from database.migrations.test_board_data import run as migrate_test_board_data
from infrastructure.db.base import SessionLocal, engine

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("database_migration")


async def _user_count() -> int:
    async with SessionLocal() as db:
        return int((await db.execute(text("SELECT COUNT(*) FROM users"))).scalar_one())


async def migrate() -> None:
    if engine.dialect.name != "mysql":
        raise RuntimeError(f"Production migration requires MySQL, got {engine.dialect.name}")

    users_before = await _user_count()
    await create_tables_with_latest_schema()
    await migrate_mysql_schema()
    permission_result = await migrate_service_permissions()
    await migrate_phase_a()
    await migrate_process_runtime()
    test_board_result = await migrate_test_board_data()
    users_after = await _user_count()
    if users_after != users_before:
        raise RuntimeError(
            f"User count changed during migration: {users_before} -> {users_after}"
        )
    logger.info(
        "Migration completed; users=%d permissions=%s test_board=%s",
        users_after,
        permission_result,
        test_board_result,
    )


async def main() -> None:
    try:
        await migrate()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
