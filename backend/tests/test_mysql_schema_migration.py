from scripts.migrate_mysql_schema import (
    INDEX_MIGRATIONS,
    MIGRATION_VERSION,
    TABLE_COLUMN_MIGRATIONS,
)


def test_mysql_migration_manifest_is_mysql_only_and_complete():
    assert MIGRATION_VERSION
    assert INDEX_MIGRATIONS["test_cases"]["ix_test_cases_is_flaky_manual"] == "is_flaky_manual"
    assert set(TABLE_COLUMN_MIGRATIONS["test_cases"]) == {
        "lifetime_runs",
        "lifetime_failures",
        "issues_found",
        "suspected_test_issue_count",
        "is_flaky_manual",
    }
    assert all(
        "sqlite" not in definition.lower()
        for definitions in TABLE_COLUMN_MIGRATIONS.values()
        for definition in definitions.values()
    )
