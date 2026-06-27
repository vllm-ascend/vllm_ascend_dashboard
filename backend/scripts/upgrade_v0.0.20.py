"""Database upgrade v0.0.20 - add share_token and pdf_file_path to job_failure_analysis"""
import asyncio, logging, sys, secrets
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from sqlalchemy import text
from app.db.base import SessionLocal, engine
logger = logging.getLogger(__name__)
DESCRIPTION = "Add share_token and pdf_file_path to job_failure_analysis"
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
    print("  Starting upgrade to v0.0.20")
    print("=" * 60 + "\n")
    is_mysql = "mysql" in str(engine.url)
    async with SessionLocal() as db:
        for col, col_type in [("share_token", "VARCHAR(64) NULL"), ("pdf_file_path", "VARCHAR(200) NULL")]:
            if await check_column_exists(TABLE_NAME, col):
                print(f"  [OK] Column '{col}' already exists")
                continue
            await db.execute(text(f"ALTER TABLE {TABLE_NAME} ADD COLUMN {col} {col_type}"))
            await db.commit()
            print(f"  [OK] Added column '{col}'")
            if col == "share_token" and is_mysql:
                try:
                    await db.execute(text(f"CREATE UNIQUE INDEX ix_{TABLE_NAME}_share_token ON {TABLE_NAME}(share_token)"))
                    await db.commit()
                except Exception:
                    pass
    # Backfill share_token for existing completed analyses
    async with SessionLocal() as db:
        result = await db.execute(text(f"SELECT id FROM {TABLE_NAME} WHERE share_token IS NULL AND analysis_status = 'completed'"))
        rows = result.fetchall()
        for row in rows:
            token = secrets.token_urlsafe(32)
            await db.execute(text(f"UPDATE {TABLE_NAME} SET share_token = :t WHERE id = :i"), {"t": token, "i": row[0]})
        await db.commit()
        if rows:
            print(f"  [OK] Generated share_token for {len(rows)} existing analyses")
    print("\n" + "=" * 60 + "\n  [OK] Upgrade to v0.0.20 completed!\n" + "=" * 60 + "\n")

if __name__ == "__main__":
    asyncio.run(upgrade())
