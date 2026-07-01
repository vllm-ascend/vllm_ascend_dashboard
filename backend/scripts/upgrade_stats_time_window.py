"""
Migration: Add stats_start_hour and stats_end_hour to workflow_configs

Adds configurable time window fields for CI statistics filtering.
Default: nightly workflows get 21:00-03:00, others get NULL (no filter).
"""
import asyncio
import os
import aiomysql


async def migrate():
    conn = await aiomysql.connect(
        host=os.environ.get("MYSQL_HOST", "mysql"),
        port=3306,
        user=os.environ.get("MYSQL_USER", "vllm_ascend"),
        password=os.environ.get("MYSQL_PASSWORD", "openlab123"),
        db=os.environ.get("MYSQL_DATABASE", "vllm_dashboard"),
    )
    cur = await conn.cursor()

    # Check if columns already exist
    await cur.execute("""
        SELECT COUNT(*) FROM information_schema.columns
        WHERE table_name = 'workflow_configs'
        AND column_name IN ('stats_start_hour', 'stats_end_hour')
    """)
    count = (await cur.fetchone())[0]

    if count >= 2:
        print("Columns already exist, skipping migration.")
    else:
        print("Adding stats_start_hour and stats_end_hour columns...")
        await cur.execute("ALTER TABLE workflow_configs ADD COLUMN stats_start_hour INT NULL")
        await cur.execute("ALTER TABLE workflow_configs ADD COLUMN stats_end_hour INT NULL")
        print("Columns added.")

        # Set default time window for nightly workflows
        await cur.execute("""
            UPDATE workflow_configs
            SET stats_start_hour = 21, stats_end_hour = 3
            WHERE workflow_name LIKE '%nightly%' AND stats_start_hour IS NULL
        """)
        updated = cur.rowcount
        print(f"Set default 21:00-03:00 for {updated} nightly workflow(s).")

    await conn.commit()

    # Verify
    await cur.execute("SELECT workflow_name, stats_start_hour, stats_end_hour FROM workflow_configs")
    rows = await cur.fetchall()
    print("\nCurrent workflow configs:")
    for row in rows:
        print(f"  {row[0]}: start={row[1]}, end={row[2]}")

    await cur.close()
    conn.close()
    print("\nMigration complete.")


if __name__ == "__main__":
    asyncio.run(migrate())
