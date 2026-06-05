"""
Database upgrade script v0.0.8

Add daily_report_history table for email report sending records.
"""
import asyncio
import logging

from sqlalchemy import inspect, text

from app.db.base import SessionLocal, engine

logger = logging.getLogger(__name__)

DESCRIPTION = "Add daily_report_history table for email report sending records"


async def check_table_exists(table_name: str) -> bool:
    try:
        def _get_table_names(conn):
            inspector = inspect(conn)
            return inspector.get_table_names()

        async with engine.begin() as conn:
            table_names = await conn.run_sync(_get_table_names)
            return table_name in table_names
    except Exception:
        return False


async def upgrade():
    print("\n" + "=" * 60)
    print("  Starting upgrade to v0.0.8")
    print("=" * 60 + "\n")

    table_name = "daily_report_history"
    if await check_table_exists(table_name):
        print(f"  ✓ Table {table_name} already exists")
        return

    is_mysql = "mysql" in str(engine.url)
    if is_mysql:
        create_table_sql = """
        CREATE TABLE daily_report_history (
            id INTEGER PRIMARY KEY AUTO_INCREMENT,
            report_date VARCHAR(10) NOT NULL,
            recipients TEXT NOT NULL,
            subject VARCHAR(200) NOT NULL,
            status VARCHAR(20) DEFAULT 'pending',
            sent_at TIMESTAMP NULL,
            error_message TEXT NULL,
            ci_summary JSON NULL,
            model_summary JSON NULL,
            github_summary JSON NULL,
            performance_summary JSON NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX ix_report_date (report_date),
            INDEX ix_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    else:
        create_table_sql = """
        CREATE TABLE daily_report_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date VARCHAR(10) NOT NULL,
            recipients TEXT NOT NULL,
            subject VARCHAR(200) NOT NULL,
            status VARCHAR(20) DEFAULT 'pending',
            sent_at TIMESTAMP,
            error_message TEXT,
            ci_summary TEXT,
            model_summary TEXT,
            github_summary TEXT,
            performance_summary TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """

    create_index_sql_statements = [
        "CREATE INDEX IF NOT EXISTS ix_daily_report_history_report_date ON daily_report_history (report_date)",
        "CREATE INDEX IF NOT EXISTS ix_daily_report_history_status ON daily_report_history (status)",
    ]

    async with SessionLocal() as db:
        try:
            await db.execute(text(create_table_sql))
            if not is_mysql:
                for idx_sql in create_index_sql_statements:
                    try:
                        await db.execute(text(idx_sql))
                    except Exception:
                        pass
            await db.commit()
            print("  ✅ Created table daily_report_history")
        except Exception as exc:
            await db.rollback()
            logger.error("Upgrade v0.0.8 failed: %s", exc, exc_info=True)
            print(f"\n  ❌ Upgrade failed: {exc}")
            raise

    print("\n" + "=" * 60)
    print("  ✅ Upgrade to v0.0.8 completed successfully!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())