"""Database upgrade v0.0.25 - clean up non-test job cases and duplicate test names"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.db.base import SessionLocal

logger = logging.getLogger(__name__)
DESCRIPTION = "Delete non-test job test cases and duplicate test names with ' / ' suffix"


async def upgrade():
    print("\n" + "=" * 60)
    print("  Starting upgrade to v0.0.25")
    print("=" * 60 + "\n")

    async with SessionLocal() as db:
        # 1. Delete non-test job test cases (build/setup/cleanup jobs)
        non_test_patterns = [
            "Build %", "Export %", "Merge %", "clear-pre-logs",
            "Parse trigger%", "Generate %",
        ]
        total_deleted = 0
        for pattern in non_test_patterns:
            result = await db.execute(text(
                "SELECT COUNT(*) FROM test_cases WHERE test_name LIKE :pattern"
            ), {"pattern": pattern})
            count = result.scalar()
            if count and count > 0:
                await db.execute(text(
                    "DELETE FROM test_runs WHERE test_case_id IN "
                    "(SELECT id FROM test_cases WHERE test_name LIKE :pattern)"
                ), {"pattern": pattern})
                await db.execute(text(
                    "DELETE FROM test_cases WHERE test_name LIKE :pattern"
                ), {"pattern": pattern})
                total_deleted += count
                print(f"  [DONE] Deleted {count} cases matching '{pattern}'")
        await db.commit()
        if total_deleted:
            print(f"  Total non-test cases deleted: {total_deleted}")
        else:
            print("  [OK] No non-test cases found")

        # 2. Delete duplicate test cases (those with ' / ' suffix)
        result = await db.execute(text(
            "SELECT COUNT(*) FROM test_cases WHERE test_name LIKE '% / %'"
        ))
        dup_count = result.scalar()
        if dup_count and dup_count > 0:
            await db.execute(text(
                "DELETE FROM test_runs WHERE test_case_id IN "
                "(SELECT id FROM test_cases WHERE test_name LIKE '% / %')"
            ))
            await db.execute(text(
                "DELETE FROM test_cases WHERE test_name LIKE '% / %'"
            ))
            await db.commit()
            print(f"  [DONE] Deleted {dup_count} duplicate cases with ' / ' suffix")
        else:
            print("  [OK] No duplicate cases found")

        # 3. Verify
        result = await db.execute(text("SELECT COUNT(*) FROM test_cases"))
        final = result.scalar()
        print(f"\n  Final test case count: {final}")

    print("\n" + "=" * 60)
    print("  Upgrade v0.0.25 complete!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
