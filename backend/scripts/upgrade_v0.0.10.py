"""
Database upgrade script v0.0.10

Add alert_rules and alert_history tables for user-customizable alert rules.
"""
import asyncio
import logging

from sqlalchemy import inspect, text

from app.db.base import SessionLocal, engine

logger = logging.getLogger(__name__)

DESCRIPTION = "Add alert_rules and alert_history tables for user-customizable alert rules"


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
    print("  Starting upgrade to v0.0.10")
    print("=" * 60 + "\n")

    is_mysql = "mysql" in str(engine.url)
    created_any = False

    # --- alert_rules ---
    if await check_table_exists("alert_rules"):
        print("  ✓ Table alert_rules already exists")
    else:
        if is_mysql:
            create_sql = """
            CREATE TABLE alert_rules (
                id INTEGER PRIMARY KEY AUTO_INCREMENT,
                user_id INT NOT NULL,
                name VARCHAR(100) NOT NULL,
                metric_field VARCHAR(50) NOT NULL,
                operator VARCHAR(10) NOT NULL,
                threshold DOUBLE NOT NULL,
                cluster_id INT,
                enabled BOOLEAN DEFAULT TRUE,
                notify_email BOOLEAN DEFAULT TRUE,
                notification_email VARCHAR(100),
                last_triggered_at TIMESTAMP NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX ix_alert_rules_user_id (user_id),
                INDEX ix_alert_rules_enabled (enabled)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        else:
            create_sql = """
            CREATE TABLE alert_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name VARCHAR(100) NOT NULL,
                metric_field VARCHAR(50) NOT NULL,
                operator VARCHAR(10) NOT NULL,
                threshold REAL NOT NULL,
                cluster_id INTEGER,
                enabled BOOLEAN DEFAULT 1,
                notify_email BOOLEAN DEFAULT 1,
                notification_email VARCHAR(100),
                last_triggered_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """

        async with SessionLocal() as db:
            try:
                await db.execute(text(create_sql))
                if not is_mysql:
                    for idx_sql in [
                        "CREATE INDEX ix_alert_rules_user_id ON alert_rules(user_id)",
                        "CREATE INDEX ix_alert_rules_enabled ON alert_rules(enabled)",
                    ]:
                        try:
                            await db.execute(text(idx_sql))
                        except Exception:
                            pass
                await db.commit()
                print("  ✅ Created table alert_rules")
                created_any = True
            except Exception as exc:
                await db.rollback()
                logger.error("Failed to create alert_rules: %s", exc, exc_info=True)
                print(f"  ❌ Failed to create alert_rules: {exc}")
                raise

    # --- alert_history ---
    if await check_table_exists("alert_history"):
        print("  ✓ Table alert_history already exists")
    else:
        if is_mysql:
            create_sql = """
            CREATE TABLE alert_history (
                id INTEGER PRIMARY KEY AUTO_INCREMENT,
                rule_id INT NOT NULL,
                rule_name VARCHAR(100) NOT NULL,
                metric_field VARCHAR(50) NOT NULL,
                operator VARCHAR(10) NOT NULL,
                threshold DOUBLE NOT NULL,
                actual_value DOUBLE NOT NULL,
                cluster_id INT,
                cluster_name VARCHAR(100),
                triggered_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                notification_sent BOOLEAN DEFAULT FALSE,
                notification_error TEXT,
                INDEX ix_alert_history_rule_id (rule_id),
                INDEX ix_alert_history_triggered_at (triggered_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        else:
            create_sql = """
            CREATE TABLE alert_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id INTEGER NOT NULL,
                rule_name VARCHAR(100) NOT NULL,
                metric_field VARCHAR(50) NOT NULL,
                operator VARCHAR(10) NOT NULL,
                threshold REAL NOT NULL,
                actual_value REAL NOT NULL,
                cluster_id INTEGER,
                cluster_name VARCHAR(100),
                triggered_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                notification_sent BOOLEAN DEFAULT 0,
                notification_error TEXT
            )
            """

        async with SessionLocal() as db:
            try:
                await db.execute(text(create_sql))
                if not is_mysql:
                    for idx_sql in [
                        "CREATE INDEX ix_alert_history_rule_id ON alert_history(rule_id)",
                        "CREATE INDEX ix_alert_history_triggered_at ON alert_history(triggered_at)",
                    ]:
                        try:
                            await db.execute(text(idx_sql))
                        except Exception:
                            pass
                await db.commit()
                print("  ✅ Created table alert_history")
                created_any = True
            except Exception as exc:
                await db.rollback()
                logger.error("Failed to create alert_history: %s", exc, exc_info=True)
                print(f"  ❌ Failed to create alert_history: {exc}")
                raise

    if not created_any:
        print("  ℹ️  No new tables to create (all already exist)")

    print("\n" + "=" * 60)
    print("  ✅ Upgrade to v0.0.10 completed successfully!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
