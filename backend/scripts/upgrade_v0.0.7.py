"""
Database upgrade script v0.0.7

Add namespace configuration to Kubernetes resource dashboard clusters.
"""
import asyncio
import logging

from sqlalchemy import inspect, text

from app.db.base import SessionLocal, engine

logger = logging.getLogger(__name__)

DESCRIPTION = "Add namespace configuration to Kubernetes resource dashboard clusters"


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
            return inspector.get_columns(table_name)

        async with engine.begin() as conn:
            columns = await conn.run_sync(_get_columns)
            return any(column["name"] == column_name for column in columns)
    except Exception:
        return False


async def upgrade():
    print("\n" + "=" * 60)
    print("  Starting upgrade to v0.0.7")
    print("=" * 60 + "\n")

    table_name = "kubernetes_cluster_configs"
    if not await check_table_exists(table_name):
        print(f"  ✓ Table {table_name} does not exist, skipping")
        return

    if await check_column_exists(table_name, "namespaces"):
        print("  ✓ Column namespaces already exists")
        return

    is_mysql = "mysql" in str(engine.url)
    if is_mysql:
        alter_table_sql = """
        ALTER TABLE kubernetes_cluster_configs
        ADD COLUMN namespaces VARCHAR(500) NOT NULL DEFAULT 'vllm-project'
        AFTER default_label_selector
        """
    else:
        alter_table_sql = """
        ALTER TABLE kubernetes_cluster_configs
        ADD COLUMN namespaces VARCHAR(500) NOT NULL DEFAULT 'vllm-project'
        """

    async with SessionLocal() as db:
        try:
            await db.execute(text(alter_table_sql))
            await db.commit()
            print("  ✅ Added column kubernetes_cluster_configs.namespaces")
        except Exception as exc:
            await db.rollback()
            logger.error("Upgrade v0.0.7 failed: %s", exc, exc_info=True)
            print(f"\n  ❌ Upgrade failed: {exc}")
            raise

    print("\n" + "=" * 60)
    print("  ✅ Upgrade to v0.0.7 completed successfully!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
