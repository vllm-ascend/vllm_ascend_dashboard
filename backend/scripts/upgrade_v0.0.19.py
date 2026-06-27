"""
Database upgrade script v0.0.19

Add unified log center: app_logs table for persisting application logs.
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.db.base import SessionLocal, engine

logger = logging.getLogger(__name__)

DESCRIPTION = "Add app_logs table for unified log center"


async def check_table_exists(table_name: str) -> bool:
    """Check if table exists (cross-engine: MySQL / SQLite)."""
    try:
        async with engine.begin() as conn:
            result = await conn.run_sync(
                lambda sync_conn: sync_conn.execute(
                    text(
                        "SELECT COUNT(*) FROM information_schema.tables "
                        "WHERE table_name = :name"
                    ),
                    {"name": table_name},
                )
            )
            row = result.fetchone()
            return row is not None and row[0] > 0
    except Exception:
        try:
            async with engine.begin() as conn:
                result = await conn.run_sync(
                    lambda sync_conn: sync_conn.execute(
                        text(
                            f"SELECT name FROM sqlite_master "
                            f"WHERE type='table' AND name='{table_name}'"
                        )
                    )
                )
                return result.fetchone() is not None
        except Exception:
            return False


async def upgrade():
    print("\n" + "=" * 60)
    print("  Starting upgrade to v0.0.19")
    print("=" * 60 + "\n")

    if await check_table_exists("app_logs"):
        print("  [OK] Table 'app_logs' already exists")
    else:
        async with SessionLocal() as db:
            try:
                # Try MySQL with FULLTEXT ngram parser
                await db.execute(text("""
                    CREATE TABLE app_logs (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        timestamp DATETIME(3) NOT NULL
                            COMMENT 'log timestamp',
                        level VARCHAR(10) NOT NULL
                            COMMENT 'DEBUG/INFO/WARNING/ERROR',
                        module VARCHAR(200)
                            COMMENT 'source module name',
                        function_name VARCHAR(200)
                            COMMENT 'function name',
                        line_number INT
                            COMMENT 'source line number',
                        message TEXT NOT NULL
                            COMMENT 'log message body',
                        traceback TEXT
                            COMMENT 'exception traceback if any',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_app_logs_timestamp (timestamp),
                        INDEX idx_app_logs_level (level),
                        INDEX idx_app_logs_module (module),
                        FULLTEXT INDEX ft_app_logs_message (message)
                            WITH PARSER ngram
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                      COLLATE=utf8mb4_unicode_ci
                """))
                await db.commit()
                print("  [OK] Created table 'app_logs' with FULLTEXT ngram index")
            except Exception as e:
                await db.rollback()
                logger.warning(
                    "FULLTEXT ngram not supported, falling back: %s", e
                )
                try:
                    await db.execute(text("""
                        CREATE TABLE app_logs (
                            id BIGINT AUTO_INCREMENT PRIMARY KEY,
                            timestamp DATETIME(3) NOT NULL,
                            level VARCHAR(10) NOT NULL,
                            module VARCHAR(200),
                            function_name VARCHAR(200),
                            line_number INT,
                            message TEXT NOT NULL,
                            traceback TEXT,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            INDEX idx_app_logs_timestamp (timestamp),
                            INDEX idx_app_logs_level (level),
                            INDEX idx_app_logs_module (module)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                          COLLATE=utf8mb4_unicode_ci
                    """))
                    await db.commit()
                    print("  [OK] Created table 'app_logs' (without FULLTEXT)")
                except Exception as e2:
                    await db.rollback()
                    try:
                        await db.execute(text("""
                            CREATE TABLE app_logs (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                timestamp DATETIME NOT NULL,
                                level VARCHAR(10) NOT NULL,
                                module VARCHAR(200),
                                function_name VARCHAR(200),
                                line_number INT,
                                message TEXT NOT NULL,
                                traceback TEXT,
                                created_at DATETIME
                                    DEFAULT CURRENT_TIMESTAMP
                            )
                        """))
                        await db.commit()
                        print("  [OK] Created table 'app_logs' (SQLite)")
                    except Exception as e3:
                        await db.rollback()
                        logger.error(
                            "Failed to create app_logs: %s", e3
                        )
                        print(f"  [FAIL] {e3}")
                        raise

    # Ensure indexes (idempotent, needed for SQLite)
    try:
        async with SessionLocal() as db:
            for idx_sql in [
                "CREATE INDEX IF NOT EXISTS idx_app_logs_timestamp "
                "ON app_logs(timestamp)",
                "CREATE INDEX IF NOT EXISTS idx_app_logs_level "
                "ON app_logs(level)",
                "CREATE INDEX IF NOT EXISTS idx_app_logs_module "
                "ON app_logs(module)",
            ]:
                try:
                    await db.execute(text(idx_sql))
                    await db.commit()
                except Exception:
                    await db.rollback()
            print("  [OK] Indexes ensured")
    except Exception as e:
        logger.warning("Index creation skipped: %s", e)

    print("\n" + "=" * 60)
    print("  [OK] Upgrade to v0.0.19 completed successfully!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
