"""Database upgrade v0.0.27 - add author_email column to pull_requests"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.db.base import SessionLocal, engine

logger = logging.getLogger(__name__)
DESCRIPTION = "Add author_email column to pull_requests for company detection"


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
    print("  Starting upgrade to v0.0.27")
    print("=" * 60 + "\n")

    async with SessionLocal() as db:
        if await check_column_exists("pull_requests", "author_email"):
            print("  [OK] Column 'author_email' already exists")
        else:
            await db.execute(text(
                "ALTER TABLE pull_requests ADD COLUMN author_email VARCHAR(200)"
            ))
            await db.commit()
            print("  [DONE] Added column 'author_email' to pull_requests")

    print("\n" + "=" * 60)
    print("  Upgrade v0.0.27 complete!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
