"""
Database upgrade script v0.0.4

Changes:
1. Drop daily data tables (daily_prs, daily_issues, daily_commits, daily_summaries)
2. Data has been migrated to file storage (data/daily-data/{project}/)

DESCRIPTION: Remove deprecated daily data tables after migration to file storage
"""
import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import text, inspect

from app.db.base import SessionLocal, engine
from app.services.daily_data_file_store import DailyDataFileStore

logger = logging.getLogger(__name__)

DESCRIPTION = "Drop deprecated daily data tables after migration to file storage"

# Tables to drop
TABLES_TO_DROP = [
    "daily_prs",
    "daily_issues",
    "daily_commits",
    "daily_summaries",
]


def is_mysql() -> bool:
    """Check if database is MySQL"""
    dialect_name = engine.dialect.name.lower()
    return 'mysql' in dialect_name


async def check_table_exists(table_name: str) -> bool:
    """Check if table exists (works with both MySQL and SQLite)"""
    try:
        async with engine.begin() as conn:
            def _get_table_names(connection):
                inspector = inspect(connection)
                return inspector.get_table_names()

            table_names = await conn.run_sync(_get_table_names)
            return table_name in table_names
    except Exception as e:
        logger.warning(f"Error checking table {table_name}: {e}")
        return False


async def drop_table(table_name: str) -> bool:
    """Drop a table if it exists"""
    async with SessionLocal() as db:
        try:
            exists = await check_table_exists(table_name)
            if not exists:
                print(f"   ⏭️  Table {table_name} does not exist, skipping")
                return True

            print(f"   🗑️  Dropping table: {table_name}")
            if is_mysql():
                await db.execute(text(f"DROP TABLE `{table_name}`"))
            else:
                await db.execute(text(f"DROP TABLE IF EXISTS `{table_name}`"))

            await db.commit()
            print(f"   ✅ Dropped {table_name}")
            return True

        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to drop table {table_name}: {e}", exc_info=True)
            print(f"   ❌ Failed to drop {table_name}: {e}")
            return False


async def verify_file_migration() -> bool:
    """Verify that data has been migrated to file storage"""
    file_store = DailyDataFileStore()

    if not file_store.base_dir.exists():
        print(f"   ⚠️  File storage directory does not exist: {file_store.base_dir}")
        print("   Please run the data migration script first:")
        print("   python -m scripts.migrate_daily_data_to_files")
        return False

    project_dirs = [d for d in file_store.base_dir.iterdir() if d.is_dir()]
    if not project_dirs:
        print("   ⚠️  No project directories found in file storage")
        print("   Please run the data migration script first:")
        print("   python -m scripts.migrate_daily_data_to_files")
        return False

    total_files = 0
    for project_dir in project_dirs:
        data_files = list(project_dir.glob("*.json"))
        summary_dir = project_dir / "summaries"
        summary_files = list(summary_dir.glob("*.md")) if summary_dir.exists() else []
        total_files += len(data_files) + len(summary_files)

    if total_files == 0:
        print("   ⚠️  No migrated files found in file storage")
        print("   Please run the data migration script first:")
        print("   python -m scripts.migrate_daily_data_to_files")
        return False

    print(f"   ✅ Verified {total_files} files in file storage across {len(project_dirs)} projects")
    return True


async def upgrade():
    """Run the upgrade"""
    logger.info("Starting upgrade v0.0.4...")
    print("🚀 Running upgrade v0.0.4")
    print("📝 Dropping deprecated daily data tables\n")

    # Step 1: Verify file migration
    print("1️⃣  Verifying file migration...")
    if not await verify_file_migration():
        print("\n   ❌ Migration verification failed!")
        print("   Aborting upgrade. Please migrate data first.")
        return False
    print()

    # Step 2: Drop tables
    print("2️⃣  Dropping deprecated tables...")
    success = True
    for table in TABLES_TO_DROP:
        if not await drop_table(table):
            success = False
    print()

    if success:
        print("="*60)
        print("✅ Upgrade v0.0.4 completed successfully!")
        print("   Dropped tables: " + ", ".join(TABLES_TO_DROP))
        print("="*60)
    else:
        print("="*60)
        print("⚠️  Upgrade v0.0.4 completed with warnings")
        print("="*60)

    return success


async def rollback():
    """Rollback the upgrade (recreate tables using init_db logic)"""
    logger.info("Rolling back upgrade v0.0.4...")
    print("🔙 Rolling back upgrade v0.0.4\n")
    print("   ⚠️  Rollback requires recreating tables from scratch.")
    print("   This will NOT restore data that was deleted.")
    print("   Please restore from database backup if you need the data.\n")

    confirm = input("   Type 'YES' to confirm rollback: ")
    if confirm != "YES":
        print("   Rollback cancelled.")
        return False

    print("\n   Running init_db.py to recreate tables...")
    try:
        # Import and run init_db table creation
        from scripts.init_db import create_tables_with_latest_schema
        await create_tables_with_latest_schema()
        print("\n   ✅ Tables recreated successfully!")
        print("   ⚠️  Note: Data must be restored from backup or re-migrated.")
        return True
    except Exception as e:
        logger.error(f"Rollback failed: {e}", exc_info=True)
        print(f"\n   ❌ Rollback failed: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "rollback":
            success = asyncio.run(rollback())
            sys.exit(0 if success else 1)
        elif sys.argv[1] == "help":
            print(f"""
Upgrade Script v0.0.4 - Drop deprecated daily data tables

Usage:
    python scripts/upgrade_v0.0.4.py        # Run upgrade
    python scripts/upgrade_v0.0.4.py rollback  # Rollback upgrade
    python scripts/upgrade_v0.0.4.py help      # Show help

Description:
    Removes daily data tables (daily_prs, daily_issues, daily_commits, daily_summaries)
    after data has been migrated to file storage.

    Prerequisites:
    1. Run data migration script first:
       python -m scripts.migrate_daily_data_to_files --cleanup
    2. Verify file storage contains migrated data
    3. Backup database before running this upgrade
""")
        else:
            print(f"Unknown command: {sys.argv[1]}")
            print("Use 'python scripts/upgrade_v0.0.4.py help' for usage")
            sys.exit(1)
    else:
        success = asyncio.run(upgrade())
        sys.exit(0 if success else 1)
