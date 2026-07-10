"""
Database upgrade script v0.0.11

Add resource_node_metrics table and node_name column to alert_rules / alert_history.
"""
import asyncio
import logging

from sqlalchemy import inspect, text

from app.db.base import SessionLocal, engine

logger = logging.getLogger(__name__)

DESCRIPTION = "Add resource_node_metrics table and node_name to alert tables"


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


async def check_column_exists(table_name: str, column_name: str) -> bool:
    try:
        def _get_columns(conn):
            inspector = inspect(conn)
            return [col["name"] for col in inspector.get_columns(table_name)]
        async with engine.begin() as conn:
            columns = await conn.run_sync(_get_columns)
            return column_name in columns
    except Exception:
        return False


async def upgrade():
    print("\n" + "=" * 60)
    print("  Starting upgrade to v0.0.11")
    print("=" * 60 + "\n")

    is_mysql = "mysql" in str(engine.url)
    created_any = False

    # --- resource_node_metrics ---
    if await check_table_exists("resource_node_metrics"):
        print("  ✓ Table resource_node_metrics already exists")
    else:
        if is_mysql:
            create_sql = """
            CREATE TABLE resource_node_metrics (
                id INTEGER PRIMARY KEY AUTO_INCREMENT,
                cluster_id INT NOT NULL,
                cluster_name VARCHAR(100) NOT NULL,
                node_name VARCHAR(250) NOT NULL,
                cpu_cores_total DOUBLE DEFAULT 0,
                cpu_cores_used DOUBLE DEFAULT 0,
                cpu_cores_available DOUBLE DEFAULT 0,
                cpu_utilization DOUBLE DEFAULT 0,
                memory_bytes_total DOUBLE DEFAULT 0,
                memory_bytes_used DOUBLE DEFAULT 0,
                memory_bytes_available DOUBLE DEFAULT 0,
                memory_utilization DOUBLE DEFAULT 0,
                npu_total DOUBLE DEFAULT 0,
                npu_used DOUBLE DEFAULT 0,
                npu_available DOUBLE DEFAULT 0,
                npu_utilization DOUBLE DEFAULT 0,
                executing_pods_count INT DEFAULT 0,
                collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX ix_cluster_id (cluster_id),
                INDEX ix_node_name (node_name),
                INDEX ix_collected_at (collected_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        else:
            create_sql = """
            CREATE TABLE resource_node_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cluster_id INTEGER NOT NULL,
                cluster_name VARCHAR(100) NOT NULL,
                node_name VARCHAR(250) NOT NULL,
                cpu_cores_total REAL DEFAULT 0,
                cpu_cores_used REAL DEFAULT 0,
                cpu_cores_available REAL DEFAULT 0,
                cpu_utilization REAL DEFAULT 0,
                memory_bytes_total REAL DEFAULT 0,
                memory_bytes_used REAL DEFAULT 0,
                memory_bytes_available REAL DEFAULT 0,
                memory_utilization REAL DEFAULT 0,
                npu_total REAL DEFAULT 0,
                npu_used REAL DEFAULT 0,
                npu_available REAL DEFAULT 0,
                npu_utilization REAL DEFAULT 0,
                executing_pods_count INTEGER DEFAULT 0,
                collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """

        async with SessionLocal() as db:
            try:
                await db.execute(text(create_sql))
                if not is_mysql:
                    for idx_sql in [
                        "CREATE INDEX ix_resource_node_metrics_cluster_id ON resource_node_metrics(cluster_id)",
                        "CREATE INDEX ix_resource_node_metrics_node_name ON resource_node_metrics(node_name)",
                        "CREATE INDEX ix_resource_node_metrics_collected_at ON resource_node_metrics(collected_at)",
                    ]:
                        try:
                            await db.execute(text(idx_sql))
                        except Exception:
                            pass
                await db.commit()
                print("  ✅ Created table resource_node_metrics")
                created_any = True
            except Exception as exc:
                await db.rollback()
                logger.error("Failed to create resource_node_metrics: %s", exc, exc_info=True)
                print(f"  ❌ Failed to create resource_node_metrics: {exc}")
                raise

    # --- alert_rules.node_name ---
    if not await check_column_exists("alert_rules", "node_name"):
        async with SessionLocal() as db:
            try:
                col_def = "VARCHAR(250)" if is_mysql else "VARCHAR(250)"
                await db.execute(text(f"ALTER TABLE alert_rules ADD COLUMN node_name {col_def}"))
                await db.commit()
                print("  ✅ Added column alert_rules.node_name")
                created_any = True
            except Exception as exc:
                await db.rollback()
                logger.error("Failed to add alert_rules.node_name: %s", exc, exc_info=True)
                print(f"  ❌ Failed: {exc}")
                raise
    else:
        print("  ✓ Column alert_rules.node_name already exists")

    # --- alert_history.node_name ---
    if not await check_column_exists("alert_history", "node_name"):
        async with SessionLocal() as db:
            try:
                col_def = "VARCHAR(250)" if is_mysql else "VARCHAR(250)"
                await db.execute(text(f"ALTER TABLE alert_history ADD COLUMN node_name {col_def}"))
                await db.commit()
                print("  ✅ Added column alert_history.node_name")
                created_any = True
            except Exception as exc:
                await db.rollback()
                logger.error("Failed to add alert_history.node_name: %s", exc, exc_info=True)
                print(f"  ❌ Failed: {exc}")
                raise
    else:
        print("  ✓ Column alert_history.node_name already exists")

    if not created_any:
        print("  ℹ️  No new changes needed")

    print("\n" + "=" * 60)
    print("  ✅ Upgrade to v0.0.11 completed successfully!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
