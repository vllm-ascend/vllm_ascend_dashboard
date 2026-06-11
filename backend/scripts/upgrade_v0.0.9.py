"""
Database upgrade script v0.0.9

Add resource_npu_metrics table for NPU trend data collection.
"""
import asyncio
import logging

from sqlalchemy import inspect, text

from app.db.base import SessionLocal, engine

logger = logging.getLogger(__name__)

DESCRIPTION = "Add resource_npu_metrics table for NPU trend data"


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
    print("  Starting upgrade to v0.0.9")
    print("=" * 60 + "\n")

    table_name = "resource_npu_metrics"
    if await check_table_exists(table_name):
        print(f"  ✓ Table {table_name} already exists")
        return

    is_mysql = "mysql" in str(engine.url)
    if is_mysql:
        create_table_sql = """
        CREATE TABLE resource_npu_metrics (
            id INTEGER PRIMARY KEY AUTO_INCREMENT,
            cluster_id INT NOT NULL,
            cluster_name VARCHAR(100) NOT NULL,
            npu_total DOUBLE DEFAULT 0,
            npu_used DOUBLE DEFAULT 0,
            npu_available DOUBLE DEFAULT 0,
            npu_utilization DOUBLE DEFAULT 0,
            executing_pods_count INT DEFAULT 0,
            pr_count INT DEFAULT 0,
            top_pods_json JSON,
            collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX ix_cluster_id (cluster_id),
            INDEX ix_collected_at (collected_at),
            INDEX ix_cluster_collected (cluster_id, collected_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    else:
        create_table_sql = """
        CREATE TABLE resource_npu_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cluster_id INTEGER NOT NULL,
            cluster_name VARCHAR(100) NOT NULL,
            npu_total REAL DEFAULT 0,
            npu_used REAL DEFAULT 0,
            npu_available REAL DEFAULT 0,
            npu_utilization REAL DEFAULT 0,
            executing_pods_count INTEGER DEFAULT 0,
            pr_count INTEGER DEFAULT 0,
            top_pods_json TEXT,
            collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """

    async with SessionLocal() as db:
        try:
            await db.execute(text(create_table_sql))
            if not is_mysql:
                for idx_sql in [
                    "CREATE INDEX ix_resource_npu_metrics_cluster_id ON resource_npu_metrics(cluster_id)",
                    "CREATE INDEX ix_resource_npu_metrics_collected_at ON resource_npu_metrics(collected_at)",
                    "CREATE INDEX ix_resource_npu_metrics_cluster_collected ON resource_npu_metrics(cluster_id, collected_at)",
                ]:
                    try:
                        await db.execute(text(idx_sql))
                    except Exception:
                        pass
            await db.commit()
            print("  ✅ Created table resource_npu_metrics")
        except Exception as exc:
            await db.rollback()
            logger.error("Upgrade v0.0.9 failed: %s", exc, exc_info=True)
            print(f"\n  ❌ Upgrade failed: {exc}")
            raise

    print("\n" + "=" * 60)
    print("  ✅ Upgrade to v0.0.9 completed successfully!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())