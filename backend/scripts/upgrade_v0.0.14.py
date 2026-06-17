"""
Database upgrade script v0.0.14

Add ci_failure_analysis table for Claude Code CLI powered CI failure log analysis.
"""
import asyncio
import logging

from sqlalchemy import text

from app.db.base import SessionLocal, engine

logger = logging.getLogger(__name__)

DESCRIPTION = "Add ci_failure_analysis table for AI-powered CI log analysis"


async def check_table_exists(table_name: str) -> bool:
    try:
        def _get_table_names(conn):
            from sqlalchemy import inspect
            inspector = inspect(conn)
            return inspector.get_table_names()
        async with engine.begin() as conn:
            return table_name in await conn.run_sync(_get_table_names)
    except Exception:
        return False


async def upgrade():
    print("\n" + "=" * 60)
    print("  Starting upgrade to v0.0.14")
    print("=" * 60 + "\n")

    is_mysql = "mysql" in str(engine.url)

    # ── Step 1: Create ci_failure_analysis table ──
    print("Step 1: Creating ci_failure_analysis table...")

    if await check_table_exists("ci_failure_analysis"):
        print("  ✓ ci_failure_analysis table already exists")
    else:
        if is_mysql:
            create_sql = text("""
                CREATE TABLE ci_failure_analysis (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    job_id BIGINT NOT NULL UNIQUE,
                    run_id BIGINT NOT NULL,
                    workflow_name VARCHAR(100) NOT NULL,
                    job_name VARCHAR(500),
                    root_cause_category VARCHAR(50),
                    analysis_markdown LONGTEXT,
                    suggested_fix LONGTEXT,
                    related_commits JSON,
                    confidence VARCHAR(20) DEFAULT 'medium',
                    claude_model_used VARCHAR(100),
                    claude_duration_seconds INT,
                    analyzed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_cifa_job_id (job_id),
                    INDEX idx_cifa_run_id (run_id),
                    INDEX idx_cifa_workflow (workflow_name),
                    INDEX idx_cifa_category (root_cause_category)
                )
            """)
        else:
            create_sql = text("""
                CREATE TABLE ci_failure_analysis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id BIGINT NOT NULL UNIQUE,
                    run_id BIGINT NOT NULL,
                    workflow_name VARCHAR(100) NOT NULL,
                    job_name VARCHAR(500),
                    root_cause_category VARCHAR(50),
                    analysis_markdown TEXT,
                    suggested_fix TEXT,
                    related_commits JSON,
                    confidence VARCHAR(20) DEFAULT 'medium',
                    claude_model_used VARCHAR(100),
                    claude_duration_seconds INTEGER,
                    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

        async with engine.begin() as conn:
            await conn.execute(create_sql)
        print("  ✅ ci_failure_analysis table created")

        # Create indexes for SQLite (MySQL has them inline)
        if not is_mysql:
            async with engine.begin() as conn:
                for idx_name, col in [
                    ("idx_cifa_job_id", "job_id"),
                    ("idx_cifa_run_id", "run_id"),
                    ("idx_cifa_workflow", "workflow_name"),
                    ("idx_cifa_category", "root_cause_category"),
                ]:
                    await conn.execute(text(
                        f"CREATE INDEX IF NOT EXISTS {idx_name} ON ci_failure_analysis ({col})"
                    ))
            print("  ✅ Indexes created")

    # ── Step 2: Record version ──
    print("Step 2: Recording version...")

    async with SessionLocal() as db:
        result = await db.execute(text(
            "SELECT COUNT(*) FROM database_versions WHERE version = '0.0.14'"
        ))
        if result.scalar() == 0:
            await db.execute(text(
                "INSERT INTO database_versions (version, description, applied_at) "
                "VALUES ('0.0.14', :desc, datetime('now'))"
                if not is_mysql else
                "INSERT INTO database_versions (version, description, applied_at) "
                "VALUES ('0.0.14', :desc, NOW())"
            ), {"desc": DESCRIPTION})
            await db.commit()
            print("  ✅ Version v0.0.14 recorded")
        else:
            print("  ✓ Version v0.0.14 already recorded")

    print("\n" + "=" * 60)
    print("  ✅ Upgrade to v0.0.14 completed successfully!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
