"""
Database upgrade script v0.0.6

Add Kubernetes resource dashboard cluster configuration table.
"""
import asyncio
import logging

from sqlalchemy import inspect, text

from app.db.base import SessionLocal, engine

logger = logging.getLogger(__name__)

DESCRIPTION = "Add Kubernetes resource dashboard cluster configuration table"


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
    print("  Starting upgrade to v0.0.6")
    print("=" * 60 + "\n")

    if await check_table_exists("kubernetes_cluster_configs"):
        print("  ✓ Table kubernetes_cluster_configs already exists")
        return

    is_mysql = "mysql" in str(engine.url)
    if is_mysql:
        create_table_sql = """
        CREATE TABLE kubernetes_cluster_configs (
            id INT PRIMARY KEY AUTO_INCREMENT,
            name VARCHAR(100) NOT NULL UNIQUE,
            description VARCHAR(500),
            kubeconfig_encrypted TEXT NOT NULL,
            context VARCHAR(200),
            default_label_selector VARCHAR(500),
            npu_resource_name VARCHAR(200) NOT NULL DEFAULT 'huawei.com/Ascend910',
            enabled BOOLEAN DEFAULT TRUE,
            display_order INT DEFAULT 0,
            created_by INT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX ix_kubernetes_cluster_configs_name (name),
            INDEX ix_kubernetes_cluster_configs_enabled (enabled),
            CONSTRAINT fk_kubernetes_cluster_configs_created_by
                FOREIGN KEY (created_by) REFERENCES users(id)
        )
        """
    else:
        create_table_sql = """
        CREATE TABLE kubernetes_cluster_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL UNIQUE,
            description VARCHAR(500),
            kubeconfig_encrypted TEXT NOT NULL,
            context VARCHAR(200),
            default_label_selector VARCHAR(500),
            npu_resource_name VARCHAR(200) NOT NULL DEFAULT 'huawei.com/Ascend910',
            enabled BOOLEAN DEFAULT 1,
            display_order INTEGER DEFAULT 0,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(created_by) REFERENCES users(id)
        )
        """

    async with SessionLocal() as db:
        try:
            await db.execute(text(create_table_sql))
            if not is_mysql:
                await db.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_kubernetes_cluster_configs_name "
                    "ON kubernetes_cluster_configs (name)"
                ))
                await db.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_kubernetes_cluster_configs_enabled "
                    "ON kubernetes_cluster_configs (enabled)"
                ))
            await db.commit()
            print("  ✅ Created table kubernetes_cluster_configs")
        except Exception as exc:
            await db.rollback()
            logger.error("Upgrade v0.0.6 failed: %s", exc, exc_info=True)
            print(f"\n  ❌ Upgrade failed: {exc}")
            raise

    print("\n" + "=" * 60)
    print("  ✅ Upgrade to v0.0.6 completed successfully!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
