"""Test that _generate_ai_report returns LLM content instead of crashing on AttributeError.

Root cause: daily_report.py:332 referenced result.model_used / result.total_tokens
which don't exist on LLMResult (only on ClaudeCodeResult). The AttributeError was
swallowed by the except block, causing the method to always return None.
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
