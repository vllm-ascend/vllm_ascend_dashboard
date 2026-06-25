"""
Database upgrade script v0.0.16

Add event and actor columns to workflow_configs table
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.db.base import SessionLocal, engine

logger = logging.getLogger(__name__)

DESCRIPTION = "Add event and actor columns to workflow_configs"

TABLE_NAME = "workflow_configs"


async def check_column_exists(table_name: str, column_name: str) -> bool:
    try:
        def _get_columns(conn):
            from sqlalchemy import inspect
            inspector = inspect(conn)
            return [col['name'] for col in inspector.get_columns(table_name)]

        async with engine.begin() as conn:
            columns = await conn.run_sync(_get_columns)
            return column_name in columns
    except Exception:
        return False


async def upgrade():
    print("\n" + "=" * 60)
    print("  Starting upgrade to v0.0.16")
    print("=" * 60 + "\n")

    async with SessionLocal() as db:
        # Add event column
        if not await check_column_exists(TABLE_NAME, "event"):
            try:
                await db.execute(text(
                    "ALTER TABLE workflow_configs ADD COLUMN event VARCHAR(50) DEFAULT 'schedule'"
                ))
                await db.commit()
                print("  [OK] Added column 'event' to workflow_configs")
            except Exception as e:
                await db.rollback()
                logger.error("Failed to add event column: %s", e)
                print(f"  [FAIL] Failed to add event column: {e}")
                raise
        else:
            print("  [OK] Column 'event' already exists")

        # Add actor column
        if not await check_column_exists(TABLE_NAME, "actor"):
            try:
                await db.execute(text(
                    "ALTER TABLE workflow_configs ADD COLUMN actor VARCHAR(100) NULL"
                ))
                await db.commit()
                print("  [OK] Added column 'actor' to workflow_configs")
            except Exception as e:
                await db.rollback()
                logger.error("Failed to add actor column: %s", e)
                print(f"  [FAIL] Failed to add actor column: {e}")
                raise
        else:
            print("  [OK] Column 'actor' already exists")

    print("\n" + "=" * 60)
    print("  [OK] Upgrade to v0.0.16 completed successfully!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
