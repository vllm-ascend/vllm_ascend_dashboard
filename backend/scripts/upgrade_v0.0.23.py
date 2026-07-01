"""Database upgrade v0.0.23 - delete historical step_level test cases (replaced by job_level)"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.db.base import SessionLocal

logger = logging.getLogger(__name__)
DESCRIPTION = "Delete historical step_level test cases (replaced by job_level)"


async def check_table_exists(table_name):
    from app.db.base import engine
    try:
        def _g(conn):
            from sqlalchemy import inspect
            return table_name in inspect(conn).get_table_names()
        async with engine.begin() as conn:
            return await conn.run_sync(_g)
    except Exception:
        return False


async def upgrade():
    print("\n" + "=" * 60)
    print("  Starting upgrade to v0.0.23")
    print("=" * 60 + "\n")

    if not await check_table_exists("test_cases"):
        print("  [SKIP] Table 'test_cases' does not exist")
        return

    async with SessionLocal() as db:
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
    print("  Upgrade v0.0.23 complete!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
