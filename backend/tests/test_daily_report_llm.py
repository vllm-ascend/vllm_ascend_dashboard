"""Tests for daily report LLM fix and scheduler SMTP query dedup.

1. _generate_ai_report must return LLM content (not None from AttributeError)
2. _send_daily_report_job must not issue duplicate SMTP config queries
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

backend_dir = str(Path(__file__).resolve().parent.parent)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.services.daily_report import DailyReportService  # noqa: E402
from app.services.llm_client import LLMResult  # noqa: E402


@pytest.fixture
def mock_db():
    """Mock async DB session that returns a fake LLMProviderConfig."""
    db = AsyncMock()

    fake_config = MagicMock()
    fake_config.provider = "openai"
    fake_config.default_model = "gpt-4"
    fake_config.api_key = "sk-test"
    fake_config.api_base_url = "https://api.openai.com/v1"

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = fake_config
    db.execute.return_value = scalar_result

    return db


@pytest.fixture
def report_data():
    return {
        "report_date": "2026-07-05",
        "yesterday": {"ci": {}, "model": {}, "github": {}, "performance": {}},
        "last_week": {"ci": {}, "model": {}, "github": {}, "performance": {}},
        "last_month": {"ci": {}, "model": {}, "github": {}, "performance": {}},
    }


class TestGenerateAiReport:
    """Verify _generate_ai_report returns LLM content after the fix."""

    @pytest.mark.asyncio
    async def test_returns_content_when_llm_succeeds(self, mock_db, report_data):
        """_generate_ai_report must return result.content, not None.

        Before the fix, result.model_used raised AttributeError (LLMResult has no
        such attribute), the except block caught it, and None was returned — so
        LLM never took effect.
        """
        service = DailyReportService(mock_db)

        fake_skill = MagicMock()
        fake_skill.content = "You are a report writer."

        fake_result = LLMResult(
            content="## 每日运行报告\n\n整体健康度: 良好",
            prompt_tokens=100,
            completion_tokens=200,
            generation_time=3,
        )

        with (
            patch(
                "app.services.skill_registry.get_skill_registry"
            ) as mock_registry,
            patch("app.services.llm_client.LLMClient") as mock_client_cls,
        ):
            mock_registry.return_value.get_skill_by_scope.return_value = fake_skill
            mock_client = MagicMock()
            mock_client.generate = AsyncMock(return_value=fake_result)
            mock_client_cls.return_value = mock_client

            result = await service._generate_ai_report(report_data)

        assert result is not None, (
            "_generate_ai_report returned None — the LLM result was discarded. "
            "Check that the logging line uses LLMResult attributes "
            "(prompt_tokens/completion_tokens), not ClaudeCodeResult attributes "
            "(model_used/total_tokens)."
        )
        assert "每日运行报告" in result

    @pytest.mark.asyncio
    async def test_returns_none_when_no_llm_config(self, report_data):
        """When no active LLMProviderConfig exists, return None gracefully."""
        db = AsyncMock()
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none.return_value = None
        db.execute.return_value = scalar_result

        service = DailyReportService(db)
        result = await service._generate_ai_report(report_data)
        assert result is None

    @pytest.mark.asyncio
    async def test_llm_result_attributes_match_usage(self):
        """Guard: LLMResult must NOT have model_used / total_tokens attributes.

        This test documents the root cause and prevents regressions if someone
        accidentally adds those attributes without updating callers.
        """
        r = LLMResult(
            content="x", prompt_tokens=1, completion_tokens=2, generation_time=0
        )
        assert not hasattr(r, "model_used"), (
            "LLMResult now has model_used — if this is intentional, update "
            "_generate_ai_report to use it."
        )
        assert not hasattr(r, "total_tokens"), (
            "LLMResult now has total_tokens — if this is intentional, update "
            "_generate_ai_report to use it."
        )
        assert r.prompt_tokens + r.completion_tokens == 3


# ---------------------------------------------------------------------------
# Scheduler _send_daily_report_job — SMTP query dedup + early return guards
# ---------------------------------------------------------------------------

def _make_config_row(config_value: dict):
    """Create a mock ProjectDashboardConfig row."""
    row = MagicMock()
    row.config_value = config_value
    return row


def _make_mock_session(execute_results: list):
    """Create a mock async DB session that returns results in sequence.

    Each call to session.execute() pops the next result from execute_results.
    Raises if exhausted — this catches duplicate queries (the bug we fixed).
    """
    session = AsyncMock()
    call_log: list = []

    async def fake_execute(stmt):
        call_log.append(stmt)
        if not execute_results:
            raise AssertionError(
                f"DB execute() called {len(call_log)} times but only "
                f"{len(call_log) - 1} results were expected — duplicate query detected"
            )
        result = MagicMock()
        result.scalar_one_or_none.return_value = execute_results.pop(0)
        return result

    session.execute = fake_execute
    session.call_log = call_log
    return session


def _patch_scheduler_job(mock_session, mock_send=None):
    """Return a contextmanager that patches all dependencies of _send_daily_report_job."""
    mock_engine = MagicMock()
    mock_engine.dispose = AsyncMock()

    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_session
    mock_cm.__aexit__.return_value = None
    mock_session_factory = MagicMock(return_value=mock_cm)

    patches = [
        patch("app.services.scheduler.settings"),
        patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_engine),
        patch("sqlalchemy.orm.sessionmaker", return_value=mock_session_factory),
    ]
    if mock_send is not None:
        patches.append(
            patch("app.services.daily_report.DailyReportService.send_report", new=mock_send)
        )
    return patches


class TestSendDailyReportJobSmtpDedup:
    """Verify _send_daily_report_job reads SMTP config exactly once."""

    @pytest.mark.asyncio
    async def test_no_duplicate_smtp_query_when_smtp_missing(self):
        """SMTP config must be queried only once, not twice.

        Before the fix, lines 729-735 issued a second identical SELECT for
        smtp_config. This test fails if the duplicate is reintroduced.
        """
        from app.services.scheduler import DataSyncScheduler

        scheduler = DataSyncScheduler.__new__(DataSyncScheduler)

        report_config_row = _make_config_row({"report_recipients": "a@b.com"})
        smtp_config_row = _make_config_row({"smtp_host": ""})
        mock_session = _make_mock_session([report_config_row, smtp_config_row])
        mock_send = AsyncMock()

        patches = _patch_scheduler_job(mock_session, mock_send)
        for p in patches:
            p.start()
        try:
            import app.services.scheduler as sched_mod
            sched_mod.settings.REPORT_ENABLED = True
            sched_mod.settings.DATABASE_URL = "sqlite+aiosqlite:///:memory:"

            await scheduler._send_daily_report_job()
        finally:
            for p in patches:
                p.stop()

        mock_send.assert_not_called()
        assert len(mock_session.call_log) == 2, (
            f"Expected exactly 2 DB queries (report_config + smtp_config), "
            f"got {len(mock_session.call_log)} — duplicate SMTP query may be back"
        )

    @pytest.mark.asyncio
    async def test_skips_when_no_recipients(self):
        """Job must return early when report_recipients is empty."""
        from app.services.scheduler import DataSyncScheduler

        scheduler = DataSyncScheduler.__new__(DataSyncScheduler)

        report_config_row = _make_config_row({"report_recipients": ""})
        smtp_config_row = _make_config_row({"smtp_host": "smtp.example.com"})
        mock_session = _make_mock_session([report_config_row, smtp_config_row])
        mock_send = AsyncMock()

        patches = _patch_scheduler_job(mock_session, mock_send)
        for p in patches:
            p.start()
        try:
            import app.services.scheduler as sched_mod
            sched_mod.settings.REPORT_ENABLED = True
            sched_mod.settings.DATABASE_URL = "sqlite+aiosqlite:///:memory:"

            await scheduler._send_daily_report_job()
        finally:
            for p in patches:
                p.stop()

        mock_send.assert_not_called()
