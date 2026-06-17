"""
Database upgrade script v0.0.15

Add pull_requests table for PR Pipeline Kanban
"""
import asyncio
import logging

from sqlalchemy import inspect, text

from app.db.base import SessionLocal, engine

logger = logging.getLogger(__name__)

DESCRIPTION = "Add pull_requests table for PR Pipeline Kanban"


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
    print("  Starting upgrade to v0.0.15")
    print("=" * 60 + "\n")

    table_name = "pull_requests"
    if await check_table_exists(table_name):
        print(f"  [OK] Table {table_name} already exists")
        return

    is_mysql = "mysql" in str(engine.url)
    if is_mysql:
        create_table_sql = """
        CREATE TABLE pull_requests (
            id INTEGER PRIMARY KEY AUTO_INCREMENT,
            pr_number BIGINT NOT NULL,
            owner VARCHAR(100) NOT NULL,
            repo VARCHAR(100) NOT NULL,
            title VARCHAR(500) NOT NULL,
            author VARCHAR(100) NOT NULL,
            author_avatar_url VARCHAR(500),
            html_url VARCHAR(500),
            state VARCHAR(20) NOT NULL,
            is_draft BOOLEAN DEFAULT 0,
            labels JSON,
            head_branch VARCHAR(200),
            head_sha VARCHAR(40),
            base_branch VARCHAR(200),
            additions INTEGER DEFAULT 0,
            deletions INTEGER DEFAULT 0,
            changed_files INTEGER DEFAULT 0,
            pipeline_stage VARCHAR(20),
            review_status VARCHAR(20),
            reviewers JSON,
            ci_status VARCHAR(20),
            ci_workflow_run_id BIGINT,
            first_review_at DATETIME,
            first_approved_at DATETIME,
            ci_started_at DATETIME,
            ci_completed_at DATETIME,
            merged_at DATETIME,
            closed_at DATETIME,
            created_at DATETIME NOT NULL,
            updated_at DATETIME,
            data JSON,
            UNIQUE INDEX uq_pr_owner_repo (pr_number, owner, repo),
            INDEX ix_pull_requests_pr_number (pr_number),
            INDEX ix_pull_requests_owner (owner),
            INDEX ix_pull_requests_repo (repo),
            INDEX ix_pull_requests_author (author),
            INDEX ix_pull_requests_state (state),
            INDEX ix_pull_requests_is_draft (is_draft),
            INDEX ix_pull_requests_head_sha (head_sha),
            INDEX ix_pull_requests_pipeline_stage (pipeline_stage),
            INDEX ix_pull_requests_review_status (review_status),
            INDEX ix_pull_requests_ci_status (ci_status),
            INDEX ix_pull_requests_created_at (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
    else:
        create_table_sql = """
        CREATE TABLE pull_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pr_number BIGINT NOT NULL,
            owner VARCHAR(100) NOT NULL,
            repo VARCHAR(100) NOT NULL,
            title VARCHAR(500) NOT NULL,
            author VARCHAR(100) NOT NULL,
            author_avatar_url VARCHAR(500),
            html_url VARCHAR(500),
            state VARCHAR(20) NOT NULL,
            is_draft BOOLEAN DEFAULT 0,
            labels TEXT,
            head_branch VARCHAR(200),
            head_sha VARCHAR(40),
            base_branch VARCHAR(200),
            additions INTEGER DEFAULT 0,
            deletions INTEGER DEFAULT 0,
            changed_files INTEGER DEFAULT 0,
            pipeline_stage VARCHAR(20),
            review_status VARCHAR(20),
            reviewers TEXT,
            ci_status VARCHAR(20),
            ci_workflow_run_id BIGINT,
            first_review_at TIMESTAMP,
            first_approved_at TIMESTAMP,
            ci_started_at TIMESTAMP,
            ci_completed_at TIMESTAMP,
            merged_at TIMESTAMP,
            closed_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            data TEXT,
            UNIQUE (pr_number, owner, repo)
        )
        """

    async with SessionLocal() as db:
        try:
            await db.execute(text(create_table_sql))
            if not is_mysql:
                for idx_sql in [
                    "CREATE INDEX ix_pull_requests_pr_number ON pull_requests(pr_number)",
                    "CREATE INDEX ix_pull_requests_owner ON pull_requests(owner)",
                    "CREATE INDEX ix_pull_requests_repo ON pull_requests(repo)",
                    "CREATE INDEX ix_pull_requests_author ON pull_requests(author)",
                    "CREATE INDEX ix_pull_requests_state ON pull_requests(state)",
                    "CREATE INDEX ix_pull_requests_is_draft ON pull_requests(is_draft)",
                    "CREATE INDEX ix_pull_requests_head_sha ON pull_requests(head_sha)",
                    "CREATE INDEX ix_pull_requests_pipeline_stage ON pull_requests(pipeline_stage)",
                    "CREATE INDEX ix_pull_requests_review_status ON pull_requests(review_status)",
                    "CREATE INDEX ix_pull_requests_ci_status ON pull_requests(ci_status)",
                    "CREATE INDEX ix_pull_requests_created_at ON pull_requests(created_at)",
                ]:
                    try:
                        await db.execute(text(idx_sql))
                    except Exception:
                        pass
            await db.commit()
            print("  [OK] Created table pull_requests")
        except Exception as exc:
            await db.rollback()
            logger.error("Upgrade v0.0.15 failed: %s", exc, exc_info=True)
            print(f"\n  [FAIL] Upgrade failed: {exc}")
            raise

    print("\n" + "=" * 60)
    print("  [OK] Upgrade to v0.0.15 completed successfully!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
