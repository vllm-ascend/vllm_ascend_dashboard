"""Database upgrade script v0.0.30

Create 5 tables for the Code Metrics Dashboard feature:
  - code_metrics_snapshots
  - code_metrics_complexity_details
  - code_metrics_duplication_details
  - code_metrics_security_details
  - code_metrics_file_heatmap
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.db.base import SessionLocal, engine

logger = logging.getLogger(__name__)
DESCRIPTION = "Create code metrics dashboard tables (snapshots, complexity/duplication/security details, file heatmap)"


async def check_table_exists(table_name: str) -> bool:
    try:
        def _get_table_names(conn):
            from sqlalchemy import inspect
            return inspect(conn).get_table_names()

        async with engine.begin() as conn:
            table_names = await conn.run_sync(_get_table_names)
            return table_name in table_names
    except Exception:
        return False


# 每张表的建表 SQL：key -> (mysql_sql, sqlite_sql)
TABLES = {
    "code_metrics_snapshots": (
        """
        CREATE TABLE IF NOT EXISTS code_metrics_snapshots (
            id INTEGER PRIMARY KEY AUTO_INCREMENT,
            repo VARCHAR(200) NOT NULL DEFAULT 'vllm-ascend',
            branch VARCHAR(100) NOT NULL DEFAULT 'main',
            snapshot_date DATE NOT NULL,
            collection_status VARCHAR(20) DEFAULT 'complete',
            collection_duration_seconds INTEGER DEFAULT 0,
            total_loc INTEGER DEFAULT 0,
            total_raw_lines INTEGER DEFAULT 0,
            loc_python INTEGER DEFAULT 0,
            loc_cpp INTEGER DEFAULT 0,
            loc_c INTEGER DEFAULT 0,
            loc_cmake INTEGER DEFAULT 0,
            loc_shell INTEGER DEFAULT 0,
            total_functions INTEGER DEFAULT 0,
            total_files INTEGER DEFAULT 0,
            cc_total INTEGER DEFAULT 0,
            cc_per_method DOUBLE DEFAULT 0,
            cc_maximum INTEGER DEFAULT 0,
            cc_huge_count INTEGER DEFAULT 0,
            cc_huge_ratio DOUBLE DEFAULT 0,
            cc_adequacy DOUBLE DEFAULT 0,
            max_depth INTEGER DEFAULT 0,
            depth_huge_count INTEGER DEFAULT 0,
            depth_huge_ratio DOUBLE DEFAULT 0,
            method_lines_total INTEGER DEFAULT 0,
            lines_per_method DOUBLE DEFAULT 0,
            huge_method_count INTEGER DEFAULT 0,
            huge_method_ratio DOUBLE DEFAULT 0,
            huge_file_count INTEGER DEFAULT 0,
            huge_headerfile_count INTEGER DEFAULT 0,
            dup_blocks INTEGER DEFAULT 0,
            dup_lines INTEGER DEFAULT 0,
            dup_ratio DOUBLE DEFAULT 0,
            unsafe_functions_count INTEGER DEFAULT 0,
            warning_suppression_count INTEGER DEFAULT 0,
            lint_errors INTEGER DEFAULT 0,
            lint_warnings INTEGER DEFAULT 0,
            todo_count INTEGER DEFAULT 0,
            fixme_count INTEGER DEFAULT 0,
            hack_count INTEGER DEFAULT 0,
            health_score DOUBLE DEFAULT 0,
            health_score_complexity DOUBLE DEFAULT 0,
            health_score_security DOUBLE DEFAULT 0,
            health_score_duplication DOUBLE DEFAULT 0,
            health_score_method_size DOUBLE DEFAULT 0,
            health_score_tech_debt DOUBLE DEFAULT 0,
            health_score_lint DOUBLE DEFAULT 0,
            module_loc JSON,
            language_loc JSON,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_snapshot_date_repo_branch UNIQUE (snapshot_date, repo, branch)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS code_metrics_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo VARCHAR(200) NOT NULL DEFAULT 'vllm-ascend',
            branch VARCHAR(100) NOT NULL DEFAULT 'main',
            snapshot_date DATE NOT NULL,
            collection_status VARCHAR(20) DEFAULT 'complete',
            collection_duration_seconds INTEGER DEFAULT 0,
            total_loc INTEGER DEFAULT 0,
            total_raw_lines INTEGER DEFAULT 0,
            loc_python INTEGER DEFAULT 0,
            loc_cpp INTEGER DEFAULT 0,
            loc_c INTEGER DEFAULT 0,
            loc_cmake INTEGER DEFAULT 0,
            loc_shell INTEGER DEFAULT 0,
            total_functions INTEGER DEFAULT 0,
            total_files INTEGER DEFAULT 0,
            cc_total INTEGER DEFAULT 0,
            cc_per_method REAL DEFAULT 0,
            cc_maximum INTEGER DEFAULT 0,
            cc_huge_count INTEGER DEFAULT 0,
            cc_huge_ratio REAL DEFAULT 0,
            cc_adequacy REAL DEFAULT 0,
            max_depth INTEGER DEFAULT 0,
            depth_huge_count INTEGER DEFAULT 0,
            depth_huge_ratio REAL DEFAULT 0,
            method_lines_total INTEGER DEFAULT 0,
            lines_per_method REAL DEFAULT 0,
            huge_method_count INTEGER DEFAULT 0,
            huge_method_ratio REAL DEFAULT 0,
            huge_file_count INTEGER DEFAULT 0,
            huge_headerfile_count INTEGER DEFAULT 0,
            dup_blocks INTEGER DEFAULT 0,
            dup_lines INTEGER DEFAULT 0,
            dup_ratio REAL DEFAULT 0,
            unsafe_functions_count INTEGER DEFAULT 0,
            warning_suppression_count INTEGER DEFAULT 0,
            lint_errors INTEGER DEFAULT 0,
            lint_warnings INTEGER DEFAULT 0,
            todo_count INTEGER DEFAULT 0,
            fixme_count INTEGER DEFAULT 0,
            hack_count INTEGER DEFAULT 0,
            health_score REAL DEFAULT 0,
            health_score_complexity REAL DEFAULT 0,
            health_score_security REAL DEFAULT 0,
            health_score_duplication REAL DEFAULT 0,
            health_score_method_size REAL DEFAULT 0,
            health_score_tech_debt REAL DEFAULT 0,
            health_score_lint REAL DEFAULT 0,
            module_loc TEXT,
            language_loc TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ),
    "code_metrics_complexity_details": (
        """
        CREATE TABLE IF NOT EXISTS code_metrics_complexity_details (
            id INTEGER PRIMARY KEY AUTO_INCREMENT,
            snapshot_id INTEGER NOT NULL,
            file_path VARCHAR(500) NOT NULL,
            function_name VARCHAR(200) NOT NULL,
            language VARCHAR(20),
            cyclomatic_complexity INTEGER,
            max_nesting_depth INTEGER,
            function_lines INTEGER,
            start_line INTEGER,
            CONSTRAINT fk_cmcd_snapshot FOREIGN KEY (snapshot_id) REFERENCES code_metrics_snapshots(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS code_metrics_complexity_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            file_path VARCHAR(500) NOT NULL,
            function_name VARCHAR(200) NOT NULL,
            language VARCHAR(20),
            cyclomatic_complexity INTEGER,
            max_nesting_depth INTEGER,
            function_lines INTEGER,
            start_line INTEGER,
            FOREIGN KEY (snapshot_id) REFERENCES code_metrics_snapshots(id)
        )
        """,
    ),
    "code_metrics_duplication_details": (
        """
        CREATE TABLE IF NOT EXISTS code_metrics_duplication_details (
            id INTEGER PRIMARY KEY AUTO_INCREMENT,
            snapshot_id INTEGER NOT NULL,
            file_a VARCHAR(500) NOT NULL,
            file_b VARCHAR(500) NOT NULL,
            lines INTEGER DEFAULT 0,
            token_count INTEGER DEFAULT 0,
            fragment TEXT,
            CONSTRAINT fk_cmdd_snapshot FOREIGN KEY (snapshot_id) REFERENCES code_metrics_snapshots(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS code_metrics_duplication_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            file_a VARCHAR(500) NOT NULL,
            file_b VARCHAR(500) NOT NULL,
            lines INTEGER DEFAULT 0,
            token_count INTEGER DEFAULT 0,
            fragment TEXT,
            FOREIGN KEY (snapshot_id) REFERENCES code_metrics_snapshots(id)
        )
        """,
    ),
    "code_metrics_security_details": (
        """
        CREATE TABLE IF NOT EXISTS code_metrics_security_details (
            id INTEGER PRIMARY KEY AUTO_INCREMENT,
            snapshot_id INTEGER NOT NULL,
            file_path VARCHAR(500) NOT NULL,
            line_number INTEGER,
            severity VARCHAR(20),
            tool VARCHAR(50),
            rule_id VARCHAR(100),
            message TEXT,
            CONSTRAINT fk_cmsd_snapshot FOREIGN KEY (snapshot_id) REFERENCES code_metrics_snapshots(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS code_metrics_security_details (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            file_path VARCHAR(500) NOT NULL,
            line_number INTEGER,
            severity VARCHAR(20),
            tool VARCHAR(50),
            rule_id VARCHAR(100),
            message TEXT,
            FOREIGN KEY (snapshot_id) REFERENCES code_metrics_snapshots(id)
        )
        """,
    ),
    "code_metrics_file_heatmap": (
        """
        CREATE TABLE IF NOT EXISTS code_metrics_file_heatmap (
            id INTEGER PRIMARY KEY AUTO_INCREMENT,
            repo VARCHAR(200) NOT NULL DEFAULT 'vllm-ascend',
            file_path VARCHAR(500) NOT NULL,
            change_count INTEGER DEFAULT 0,
            bug_fix_count INTEGER DEFAULT 0,
            last_changed DATETIME,
            last_commit_sha VARCHAR(40),
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            CONSTRAINT uq_heatmap_repo_file UNIQUE (repo, file_path)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS code_metrics_file_heatmap (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo VARCHAR(200) NOT NULL DEFAULT 'vllm-ascend',
            file_path VARCHAR(500) NOT NULL,
            change_count INTEGER DEFAULT 0,
            bug_fix_count INTEGER DEFAULT 0,
            last_changed DATETIME,
            last_commit_sha VARCHAR(40),
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ),
}

# 每张表需要创建的索引（仅 SQLite 需要手动建，MySQL 在建表语句中已包含）
SQLITE_INDEXES = {
    "code_metrics_snapshots": [
        "CREATE INDEX IF NOT EXISTS ix_cms_snapshot_date ON code_metrics_snapshots(snapshot_date)",
    ],
    "code_metrics_complexity_details": [
        "CREATE INDEX IF NOT EXISTS ix_cmcd_snapshot_id ON code_metrics_complexity_details(snapshot_id)",
    ],
    "code_metrics_duplication_details": [
        "CREATE INDEX IF NOT EXISTS ix_cmdd_snapshot_id ON code_metrics_duplication_details(snapshot_id)",
    ],
    "code_metrics_security_details": [
        "CREATE INDEX IF NOT EXISTS ix_cmsd_snapshot_id ON code_metrics_security_details(snapshot_id)",
    ],
}


async def upgrade():
    print("\n" + "=" * 60)
    print("  Starting upgrade to v0.0.30")
    print("=" * 60 + "\n")

    is_mysql = "mysql" in str(engine.url)

    for table_name, (mysql_sql, sqlite_sql) in TABLES.items():
        if await check_table_exists(table_name):
            print(f"  [OK] Table {table_name} already exists")
            continue

        create_table_sql = mysql_sql if is_mysql else sqlite_sql
        async with SessionLocal() as db:
            try:
                await db.execute(text(create_table_sql))
                if not is_mysql:
                    for idx_sql in SQLITE_INDEXES.get(table_name, []):
                        try:
                            await db.execute(text(idx_sql))
                        except Exception:
                            pass
                await db.commit()
                print(f"  [DONE] Created table {table_name}")
            except Exception as exc:
                await db.rollback()
                logger.error("Upgrade v0.0.30 failed on %s: %s", table_name, exc, exc_info=True)
                print(f"\n  [FAIL] Upgrade failed on {table_name}: {exc}")
                raise

    print("\n" + "=" * 60)
    print("  Upgrade v0.0.30 complete!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
