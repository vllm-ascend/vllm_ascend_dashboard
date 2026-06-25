"""
Database upgrade script v0.0.17

Add triggered_by column to job_failure_analysis table
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.db.base import SessionLocal, engine

logger = logging.getLogger(__name__)

DESCRIPTION = "Add triggered_by column to job_failure_analysis"

TABLE_NAME = "job_failure_analysis"


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
    print("  Starting upgrade to v0.0.17")
    print("=" * 60 + "\n")

    if await check_column_exists(TABLE_NAME, "triggered_by"):
        print("  [OK] Column 'triggered_by' already exists")
    else:
        async with SessionLocal() as db:
            try:
                await db.execute(text(
                    "ALTER TABLE job_failure_analysis ADD COLUMN triggered_by VARCHAR(20) DEFAULT 'manual'"
                ))
                await db.commit()
                print("  [OK] Added column 'triggered_by' to job_failure_analysis")
            except Exception as e:
                await db.rollback()
                logger.error("Failed to add triggered_by column: %s", e)
                print(f"  [FAIL] Failed to add triggered_by column: {e}")
                raise

    print("\n" + "=" * 60)
    print("  [OK] Upgrade to v0.0.17 completed successfully!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
