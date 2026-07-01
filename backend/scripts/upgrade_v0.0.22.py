"""Database upgrade v0.0.22 - add category column to test_cases and remap step_level test names"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.db.base import SessionLocal, engine

logger = logging.getLogger(__name__)
DESCRIPTION = "Add category to test_cases, backfill from test_suite, remap step_level test_names"
TABLE_NAME = "test_cases"


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
    print("  Starting upgrade to v0.0.22")
    print("=" * 60 + "\n")

    async with SessionLocal() as db:
        # 1. Add category column
        if await check_column_exists(TABLE_NAME, "category"):
            print("  [OK] Column 'category' already exists")
        else:
            await db.execute(text("ALTER TABLE test_cases ADD COLUMN category VARCHAR(20) NULL"))
            await db.execute(text("CREATE INDEX ix_test_cases_category ON test_cases(category)"))
            await db.commit()
            print("  [DONE] Added column 'category'")

        # 2. Backfill category from test_suite
        for pattern, cat in [("%nightly%", "nightly"), ("%weekly%", "weekly"),
                             ("%e2e-full%", "e2e-full"), ("%e2e_full%", "e2e-full")]:
            result = await db.execute(text(
                f"UPDATE test_cases SET category='{cat}' WHERE test_suite LIKE '{pattern}' AND category IS NULL"
            ))
            if result.rowcount:
                print(f"  [DONE] Backfilled {result.rowcount} cases as {cat}")
        result = await db.execute(text("UPDATE test_cases SET category='other' WHERE category IS NULL"))
        if result.rowcount:
            print(f"  [DONE] Backfilled {result.rowcount} cases as other")
        await db.commit()

        # 3. Delete historical step_level test cases (replaced by job_level)
        result = await db.execute(text(
            "SELECT COUNT(*) FROM test_cases WHERE data_granularity = 'step_level'"
        ))
        step_count = result.scalar()
        if step_count and step_count > 0:
            await db.execute(text(
                "DELETE FROM test_runs WHERE test_case_id IN "
                "(SELECT id FROM test_cases WHERE data_granularity = 'step_level')"
            ))
            await db.execute(text(
                "DELETE FROM test_cases WHERE data_granularity = 'step_level'"
            ))
            await db.commit()
            print(f"  [DONE] Deleted {step_count} step_level test cases (and their runs)")
        else:
            print("  [OK] No step_level test cases to delete")

    print("\n" + "=" * 60)
    print("  Upgrade v0.0.22 complete!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
