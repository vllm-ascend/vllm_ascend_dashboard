"""Database upgrade v0.0.26 - add last_pass_duration_seconds to test_cases"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.db.base import SessionLocal, engine

logger = logging.getLogger(__name__)
DESCRIPTION = "Add last_pass_duration_seconds column to test_cases"


async def check_column_exists(table_name, column_name):
    try:
        def _g(conn):
            from sqlalchemy import inspect
            return [c['name'] for c in inspect(conn).get_columns(table_name)]
        async with engine.begin() as conn:
            return column_name in await conn.run_sync(_g)
    except Exception:
        return False


async def upgrade():
    print("\n" + "=" * 60)
    print("  Starting upgrade to v0.0.26")
    print("=" * 60 + "\n")

    async with SessionLocal() as db:
        if await check_column_exists("test_cases", "last_pass_duration_seconds"):
            print("  [OK] Column 'last_pass_duration_seconds' already exists")
        else:
            await db.execute(text(
                "ALTER TABLE test_cases ADD COLUMN last_pass_duration_seconds FLOAT NULL"
            ))
            await db.commit()
            print("  [DONE] Added column 'last_pass_duration_seconds'")

            # Backfill from latest passing test run
            await db.execute(text(
                "UPDATE test_cases tc SET last_pass_duration_seconds = ("
                "  SELECT tr.duration_seconds FROM test_runs tr "
                "  WHERE tr.test_case_id = tc.id AND tr.result = 'passed' "
                "    AND tr.duration_seconds IS NOT NULL "
                "  ORDER BY tr.started_at DESC LIMIT 1"
                ")"
            ))
            await db.commit()
            result = await db.execute(text(
                "SELECT COUNT(*) FROM test_cases WHERE last_pass_duration_seconds IS NOT NULL"
            ))
            count = result.scalar()
            print(f"  [DONE] Backfilled {count} cases with last pass duration")

    print("\n" + "=" * 60)
    print("  Upgrade v0.0.26 complete!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
