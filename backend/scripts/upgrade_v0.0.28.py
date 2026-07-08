"""Database upgrade script v0.0.28

Create issue_diagnosis_history table for diagnosis history feature.
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.db.base import SessionLocal, engine

logger = logging.getLogger(__name__)
DESCRIPTION = "Create issue_diagnosis_history table for diagnosis history feature"


async def check_table_exists(table_name: str) -> bool:
    try:
        def _get_table_names(conn):
            from sqlalchemy import inspect
            return inspect(conn).get_table_names()

        async with engine.begin() as conn:
            table_names = await conn.run_sync(_get_table_names)
            return table_name in table_names
    except Exception:
        return False


async def upgrade():
    print("\n" + "=" * 60)
    print("  Starting upgrade to v0.0.28")
    print("=" * 60 + "\n")

    table_name = "issue_diagnosis_history"
    if await check_table_exists(table_name):
        print(f"  [OK] Table {table_name} already exists")
    else:
        is_mysql = "mysql" in str(engine.url)
        if is_mysql:
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS issue_diagnosis_history (
                id INTEGER PRIMARY KEY AUTO_INCREMENT,
                user_id INTEGER,
                diagnosis_type VARCHAR(20) NOT NULL,
                target_id VARCHAR(100) NOT NULL,
                target_label VARCHAR(200),
                report_content TEXT,
                model_used VARCHAR(100),
                duration_seconds DOUBLE DEFAULT 0,
                status VARCHAR(20) DEFAULT 'success',
                is_liked BOOLEAN DEFAULT FALSE,
                like_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_idh_user FOREIGN KEY (user_id) REFERENCES users(id),
                INDEX ix_idh_user_id (user_id),
                INDEX ix_idh_diagnosis_type (diagnosis_type),
                INDEX ix_idh_created_at (created_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        else:
            create_table_sql = """
            CREATE TABLE IF NOT EXISTS issue_diagnosis_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                diagnosis_type VARCHAR(20) NOT NULL,
                target_id VARCHAR(100) NOT NULL,
                target_label VARCHAR(200),
                report_content TEXT,
                model_used VARCHAR(100),
                duration_seconds REAL DEFAULT 0,
                status VARCHAR(20) DEFAULT 'success',
                is_liked BOOLEAN DEFAULT 0,
                like_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """

        async with SessionLocal() as db:
            try:
                await db.execute(text(create_table_sql))
                if not is_mysql:
                    for idx_sql in [
                        "CREATE INDEX IF NOT EXISTS ix_idh_user_id ON issue_diagnosis_history(user_id)",
                        "CREATE INDEX IF NOT EXISTS ix_idh_diagnosis_type ON issue_diagnosis_history(diagnosis_type)",
                        "CREATE INDEX IF NOT EXISTS ix_idh_created_at ON issue_diagnosis_history(created_at)",
                    ]:
                        try:
                            await db.execute(text(idx_sql))
                        except Exception:
                            pass
                await db.commit()
                print(f"  [DONE] Created table {table_name}")
            except Exception as exc:
                await db.rollback()
                logger.error("Upgrade v0.0.28 failed: %s", exc, exc_info=True)
                print(f"\n  [FAIL] Upgrade failed: {exc}")
                raise

    print("\n" + "=" * 60)
    print("  Upgrade v0.0.28 complete!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
