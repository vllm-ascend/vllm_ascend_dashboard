"""
Database upgrade script v0.0.11

DESCRIPTION: Add analysis_memories and analysis_embeddings tables for agent memory system
"""
import asyncio
import logging
from datetime import datetime

from sqlalchemy import text, inspect

from app.db.base import SessionLocal, engine

logger = logging.getLogger(__name__)

DESCRIPTION = "Add analysis_memories and analysis_embeddings tables for agent memory system"


async def check_table_exists(table_name: str) -> bool:
    """Check if table exists"""
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
    """Execute database upgrade to v0.0.11"""
    print("\n" + "=" * 60)
    print("  Starting upgrade to v0.0.11")
    print("=" * 60 + "\n")

    is_mysql = "mysql" in str(engine.url)

    async with SessionLocal() as db:
        try:
            # Step 1: Create analysis_memories table
            print("Step 1: Creating analysis_memories table...")
            if not await check_table_exists("analysis_memories"):
                if is_mysql:
                    await db.execute(text("""
                        CREATE TABLE analysis_memories (
                            id INT PRIMARY KEY AUTO_INCREMENT,
                            memory_type VARCHAR(30) NOT NULL,
                            source_id INT,
                            title VARCHAR(300),
                            content TEXT,
                            tags JSON,
                            metadata JSON,
                            summary VARCHAR(500),
                            status VARCHAR(20) DEFAULT 'active',
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            INDEX idx_memory_type (memory_type),
                            INDEX idx_source_id (source_id),
                            INDEX idx_status (status),
                            INDEX idx_created_at (created_at)
                        )
                    """))
                else:
                    await db.execute(text("""
                        CREATE TABLE analysis_memories (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            memory_type VARCHAR(30) NOT NULL,
                            source_id INTEGER,
                            title VARCHAR(300),
                            content TEXT,
                            tags JSON,
                            metadata JSON,
                            summary VARCHAR(500),
                            status VARCHAR(20) DEFAULT 'active',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """))
                    for col in ("memory_type", "source_id", "status", "created_at"):
                        await db.execute(text(
                            f"CREATE INDEX IF NOT EXISTS idx_{col} ON analysis_memories ({col})"
                        ))
                await db.commit()
                print("  [OK] analysis_memories table created")
            else:
                print("  [SKIP] analysis_memories table already exists")

            # Step 2: Create analysis_embeddings table
            print("Step 2: Creating analysis_embeddings table...")
            if not await check_table_exists("analysis_embeddings"):
                if is_mysql:
                    await db.execute(text("""
                        CREATE TABLE analysis_embeddings (
                            id INT PRIMARY KEY AUTO_INCREMENT,
                            memory_id INT NOT NULL,
                            embedding JSON,
                            model VARCHAR(50),
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                            INDEX idx_memory_id (memory_id),
                            FOREIGN KEY (memory_id) REFERENCES analysis_memories(id)
                        )
                    """))
                else:
                    await db.execute(text("""
                        CREATE TABLE analysis_embeddings (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            memory_id INTEGER NOT NULL,
                            embedding JSON,
                            model VARCHAR(50),
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (memory_id) REFERENCES analysis_memories(id)
                        )
                    """))
                    await db.execute(text(
                        "CREATE INDEX IF NOT EXISTS idx_embedding_memory_id ON analysis_embeddings (memory_id)"
                    ))
                await db.commit()
                print("  [OK] analysis_embeddings table created")
            else:
                print("  [SKIP] analysis_embeddings table already exists")

            # Step 3: Record version
            print("Step 3: Recording version...")
            result = await db.execute(text(
                "SELECT COUNT(*) FROM database_versions WHERE version = '0.0.11'"
            ))
            count = result.scalar()
            if count == 0:
                await db.execute(text(
                    """INSERT INTO database_versions (version, description, applied_at)
                       VALUES ('0.0.11', :description, :applied_at)"""
                ), {"description": DESCRIPTION, "applied_at": datetime.now()})
                await db.commit()
                print("  [OK] Version v0.0.11 recorded")
            else:
                print("  [SKIP] Version v0.0.11 already recorded")

            print("\n" + "=" * 60)
            print("  Upgrade to v0.0.11 completed!")
            print("=" * 60 + "\n")

        except Exception as e:
            await db.rollback()
            logger.error(f"Upgrade failed: {e}", exc_info=True)
            print(f"\n  [FAIL] Upgrade failed: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(upgrade())
