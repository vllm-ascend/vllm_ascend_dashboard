"""Database upgrade script v0.0.18 - add share_token to job_failure_analysis"""
import asyncio, logging, sys, secrets
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from sqlalchemy import text
from app.db.base import SessionLocal, engine
logger = logging.getLogger(__name__)
DESCRIPTION = "Add share_token column to job_failure_analysis for public sharing"
TABLE_NAME = "job_failure_analysis"

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
    print("  Starting upgrade to v0.0.18")
    print("=" * 60 + "\n")
    if await check_column_exists(TABLE_NAME, "share_token"):
        print("  [OK] Column share_token already exists")
    else:
        async with SessionLocal() as db:
            is_mysql = "mysql" in str(engine.url)
            col_type = "VARCHAR(64) NULL" if is_mysql else "VARCHAR(64)"
            await db.execute(text(f"ALTER TABLE {TABLE_NAME} ADD COLUMN share_token {col_type}"))
            if is_mysql:
                await db.execute(text(f"CREATE UNIQUE INDEX ix_{TABLE_NAME}_share_token ON {TABLE_NAME}(share_token)"))
            else:
                await db.execute(text(f"CREATE UNIQUE INDEX idx_{TABLE_NAME}_share_token ON {TABLE_NAME}(share_token)"))
            await db.commit()
            print("  [OK] Added column share_token to job_failure_analysis")

    async with SessionLocal() as db:
        result = await db.execute(text("SELECT id FROM job_failure_analysis WHERE share_token IS NULL AND analysis_status = 'completed'"))
        rows = result.fetchall()
        for row in rows:
            token = secrets.token_urlsafe(32)
            await db.execute(text("UPDATE job_failure_analysis SET share_token = :t WHERE id = :i"), {"t": token, "i": row[0]})
        await db.commit()
        if rows:
            print(f"  [OK] Generated share_token for {len(rows)} existing analyses")
    print("\n" + "=" * 60 + "\n  [OK] Upgrade to v0.0.18 completed!\n" + "=" * 60 + "\n")

if __name__ == "__main__":
    asyncio.run(upgrade())
