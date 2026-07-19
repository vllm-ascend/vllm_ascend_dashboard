"""Regression tests for compatibility migrations on existing databases."""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app import main


@pytest.mark.asyncio
async def test_column_migrations_inspect_session_connection(monkeypatch):
    """Existing tables are altered instead of silently skipping inspection."""
    engine = create_async_engine(
        "mysql+aiomysql://dashboard:dashboard123@localhost:3306/vllm_dashboard_test",
    )
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE pull_requests (id INTEGER PRIMARY KEY)"))
        await connection.execute(text("CREATE TABLE user_login_logs (id INTEGER PRIMARY KEY)"))

    monkeypatch.setattr(main, "engine", engine)

    await main._migrate_login_log_columns()
    await main._migrate_avatar_base64_column()

    async with engine.connect() as connection:
        login_columns = await connection.run_sync(
            lambda sync_connection: {
                column["name"]
                for column in inspect(sync_connection).get_columns("user_login_logs")
            }
        )
        pr_columns = await connection.run_sync(
            lambda sync_connection: {
                column["name"]
                for column in inspect(sync_connection).get_columns("pull_requests")
            }
        )

    assert {"ip_address_hashed", "login_method", "user_agent", "created_at"} <= login_columns
    assert "author_avatar_base64" in pr_columns
    await engine.dispose()
