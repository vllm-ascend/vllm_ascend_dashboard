"""Schema compatibility changes must live in the explicit MySQL migration."""

from scripts.migrate_mysql_schema import INDEX_MIGRATIONS, TABLE_COLUMN_MIGRATIONS


def test_explicit_migration_contains_all_compatibility_columns():
    assert set(TABLE_COLUMN_MIGRATIONS) == {
        "user_login_logs",
        "job_failure_analysis",
        "ci_jobs",
        "pull_requests",
        "test_cases",
    }
    assert "lifetime_runs" in TABLE_COLUMN_MIGRATIONS["test_cases"]
    assert "author_avatar_base64" in TABLE_COLUMN_MIGRATIONS["pull_requests"]
    assert INDEX_MIGRATIONS["ci_jobs"]["ix_ci_jobs_processing_status"] == "processing_status"
