"""Database upgrade script v0.0.32

Add indexes on snapshot_id for code metrics detail tables to improve query
performance for the new drill-down endpoints (/code-metrics/files, /functions,
/drilldown) and existing endpoints (get_complexity, get_duplication,
get_security) — all filter by ``WHERE snapshot_id = ?``.

Tables affected:
  - code_metrics_complexity_details.snapshot_id
  - code_metrics_duplication_details.snapshot_id
  - code_metrics_security_details.snapshot_id

This is a non-destructive, idempotent migration (CREATE INDEX IF NOT EXISTS /
check existence before CREATE INDEX on MySQL).
"""
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.db.base import SessionLocal, engine

logger = logging.getLogger(__name__)
DESCRIPTION = "Add indexes on snapshot_id for code metrics detail tables"


async def _index_exists(db, table_name: str, index_name: str) -> bool:
    """Check if an index exists (MySQL + SQLite compatible)."""
    is_mysql = "mysql" in str(engine.url)
    if is_mysql:
        result = await db.execute(text(
            "SELECT COUNT(*) FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() "
            "AND table_name = :table AND index_name = :index"
        ), {"table": table_name, "index": index_name})
    else:
        # SQLite: indexes are listed in sqlite_master by name
        result = await db.execute(text(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type = 'index' AND name = :index AND tbl_name = :table"
        ), {"table": table_name, "index": index_name})
    return (result.scalar() or 0) > 0


async def _add_index(db, table_name: str, column_name: str, index_name: str):
    """Add an index if it does not already exist."""
    if await _index_exists(db, table_name, index_name):
        print(f"  [SKIP] {index_name} already exists on {table_name}")
        return
    is_mysql = "mysql" in str(engine.url)
    if is_mysql:
        await db.execute(text(f"CREATE INDEX {index_name} ON {table_name} ({column_name})"))
    else:
        await db.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({column_name})"))
    print(f"  [OK] Created {index_name} on {table_name}({column_name})")


async def upgrade():
    print("\n" + "=" * 60)
    print("  Starting upgrade to v0.0.32")
    print("=" * 60 + "\n")

    async with SessionLocal() as db:
        try:
            # Step 1: Add indexes on snapshot_id for the 3 detail tables
            print("Step 1: Adding indexes on snapshot_id for code metrics detail tables...")
            await _add_index(
                db,
                "code_metrics_complexity_details",
                "snapshot_id",
                "ix_code_metrics_complexity_details_snapshot_id",
            )
            await _add_index(
                db,
                "code_metrics_duplication_details",
                "snapshot_id",
                "ix_code_metrics_duplication_details_snapshot_id",
            )
            await _add_index(
                db,
                "code_metrics_security_details",
                "snapshot_id",
                "ix_code_metrics_security_details_snapshot_id",
            )
            await db.commit()

            # Step 2: Record version
            print("Step 2: Recording version...")
            result = await db.execute(text(
                "SELECT COUNT(*) FROM database_versions WHERE version = '0.0.32'"
            ))
            count = result.scalar()
            if count == 0:
                await db.execute(text(
                    """INSERT INTO database_versions (version, description, applied_at)
                       VALUES ('0.0.32', :description, :applied_at)"""
                ), {"description": DESCRIPTION, "applied_at": datetime.now()})
                await db.commit()
                print("  [OK] Version v0.0.32 recorded")
            else:
                print("  [SKIP] Version v0.0.32 already recorded")

            print("\n" + "=" * 60)
            print("  Upgrade to v0.0.32 completed!")
            print("=" * 60 + "\n")

        except Exception as e:
            await db.rollback()
            logger.error(f"Upgrade failed: {e}", exc_info=True)
            print(f"\n  [FAIL] Upgrade failed: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(upgrade())
