"""Schema compatibility changes must live in the explicit MySQL migration."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from database.migrations.mysql_schema import (
    CREATE_TABLE_MIGRATIONS,
    INDEX_MIGRATIONS,
    INDEX_REPLACEMENTS,
    TABLE_COLUMN_MIGRATIONS,
)


def test_explicit_migration_contains_all_compatibility_columns():
    assert set(TABLE_COLUMN_MIGRATIONS) == {
        "user_login_logs",
        "job_failure_analysis",
        "ci_jobs",
        "pull_requests",
        "test_cases",
        "daily_failure_records",
    }
    assert "lifetime_runs" in TABLE_COLUMN_MIGRATIONS["test_cases"]
    assert "author_avatar_base64" in TABLE_COLUMN_MIGRATIONS["pull_requests"]
    # daily_failure_records: source_branch 缺失会导致 _populate_daily_failure_records
    # 写入报 1054 被静默吞掉，失败跟踪数据停滞。
    assert "source_branch" in TABLE_COLUMN_MIGRATIONS["daily_failure_records"]
    assert INDEX_MIGRATIONS["ci_jobs"]["ix_ci_jobs_processing_status"] == "processing_status"
    # 唯一索引替换：daily_failure_records 加入 source_branch 后需重建唯一索引。
    assert any(r["table"] == "daily_failure_records" for r in INDEX_REPLACEMENTS)
    # scheduler_heartbeat 表由独立调度器进程写入，需在显式建表迁移中补齐。
    assert any("scheduler_heartbeat" in stmt for stmt in CREATE_TABLE_MIGRATIONS)
