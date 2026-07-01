"""Database upgrade v0.0.21 - add stats_start_hour and stats_end_hour to workflow_configs"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from sqlalchemy import text

from app.db.base import SessionLocal, engine

logger = logging.getLogger(__name__)
DESCRIPTION = "Add stats_start_hour and stats_end_hour to workflow_configs"
TABLE_NAME = "workflow_configs"


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
    print("  Starting upgrade to v0.0.21")
    print("=" * 60 + "\n")

    async with SessionLocal() as db:
        for col in ["stats_start_hour", "stats_end_hour"]:
            if await check_column_exists(TABLE_NAME, col):
                print(f"  [OK] Column '{col}' already exists")
                continue
            await db.execute(text(f"ALTER TABLE {TABLE_NAME} ADD COLUMN {col} INT NULL"))
            print(f"  [DONE] Added column '{col}'")
        await db.commit()

        result = await db.execute(text(
            "UPDATE workflow_configs SET stats_start_hour=21, stats_end_hour=3 "
            "WHERE workflow_name LIKE '%nightly%' AND stats_start_hour IS NULL"
        ))
        await db.commit()
        print(f"  [DONE] Set default 21:00-03:00 for {result.rowcount} nightly workflow(s)")

        # Add category column to test_cases
        if await check_column_exists("test_cases", "category"):
            print("  [OK] Column 'category' already exists in test_cases")
        else:
            await db.execute(text("ALTER TABLE test_cases ADD COLUMN category VARCHAR(20) NULL"))
            await db.execute(text("CREATE INDEX ix_test_cases_category ON test_cases(category)"))
            await db.commit()
            print("  [DONE] Added column 'category' to test_cases")

            # Backfill category from test_suite (workflow name)
            await db.execute(text(
                "UPDATE test_cases SET category='nightly' WHERE test_suite LIKE '%nightly%' AND category IS NULL"
            ))
            await db.execute(text(
                "UPDATE test_cases SET category='weekly' WHERE test_suite LIKE '%weekly%' AND category IS NULL"
            ))
            await db.execute(text(
                "UPDATE test_cases SET category='e2e-full' WHERE (test_suite LIKE '%e2e-full%' OR test_suite LIKE '%e2e_full%') AND category IS NULL"
            ))
            await db.execute(text(
                "UPDATE test_cases SET category='other' WHERE category IS NULL"
            ))
            await db.commit()
            print("  [DONE] Backfilled category from test_suite")

        result = await db.execute(text(
            f"SELECT workflow_name, stats_start_hour, stats_end_hour FROM {TABLE_NAME}"
        ))
        print("\n  Current workflow configs:")
        for row in result:
            print(f"    {row[0]}: start={row[1]}, end={row[2]}")

    print("\n" + "=" * 60)
    print("  Upgrade v0.0.21 complete!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
