"""
Tests for Log Center: LogService, API routes, DBLogHandler.

Coverage:
  - LogService.get_sources()
  - LogService.query()     — filtering, search, pagination
  - LogService.get_entry()
  - Log API endpoints       — HTTP status codes, response shapes
  - DBLogHandler            — emit + queue drain
  - CLI log file parsing
  - Failure analysis file parsing
"""
import json
import logging
import os
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Ensure settings validation passes before any app imports
os.environ.setdefault(
    "JWT_SECRET", "test-jwt-secret-key-at-least-32-chars-long!!"
)
os.environ.setdefault("GITHUB_TOKEN", "github_pat_test_token_for_ci_tests")
os.environ.setdefault("GITHUB_OWNER", "vllm-ascend")
os.environ.setdefault("GITHUB_REPO", "vllm-ascend")

backend_dir = str(Path(__file__).resolve().parent.parent)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.models import Base  # noqa: E402
from app.schemas.logs import LogQueryRequest  # noqa: E402
from app.services.log_service import (  # noqa: E402
    LogService,
    _parse_cli_log_file,
    _parse_failure_analysis_file,
)


# ============================================================================
# Helpers
# ============================================================================


def _make_cli_log(
    provider: str = "anthropic",
    model: str = "claude-sonnet",
    exit_code: int = 0,
    duration: float = 5.0,
    stdout_text: str = "ok",
    stderr_text: str = "",
) -> str:
    """Build a synthetic Claude Code CLI log string."""
    return f"""\
{'=' * 60}
Claude Code CLI Call Log
{'=' * 60}
Time:      2026-06-26T10:00:00.000000+00:00
Provider:  {provider}
Model:     {model}
Route:     direct
Duration:  {duration}s
Exit Code: {exit_code}

--- SYSTEM PROMPT ---
(none)

--- USER PROMPT ---
reply 'ok'

--- STDOUT ---
{stdout_text}

--- STDERR ---
{stderr_text}

--- TOOL CALLS ---
(none)

--- RAW JSON (full CLI interaction) ---
(not available)

{'=' * 60}
"""


def _make_failure_report(
    content: str = "# Analysis Report\n\nRoot cause: test failure\n",
) -> str:
    """Build a synthetic failure analysis report."""
    return content


# ============================================================================
# Fixtures
# ============================================================================


@pytest_asyncio.fixture
async def db_with_app_logs():
    """In-memory SQLite DB with app_logs table."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: sync_conn.execute(
                text(
                    "CREATE TABLE app_logs ("
                    "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "  timestamp DATETIME NOT NULL,"
                    "  level VARCHAR(10) NOT NULL,"
                    "  module VARCHAR(200),"
                    "  function_name VARCHAR(200),"
                    "  line_number INT,"
                    "  message TEXT NOT NULL,"
                    "  traceback TEXT,"
                    "  created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
                    ")"
                )
            )
        )

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def temp_log_dirs():
    """Create temporary claude_logs and failure-analysis directories."""
    base = Path(tempfile.mkdtemp())
    cli_dir = base / "claude_logs"
    fa_dir = base / "failure-analysis"
    cli_dir.mkdir(parents=True)
    fa_dir.mkdir(parents=True)
    yield base, cli_dir, fa_dir
    # Cleanup
    import shutil

    shutil.rmtree(base, ignore_errors=True)


# ============================================================================
# File Parsing Tests
# ============================================================================


class TestParseCliLogFile:
    def test_parse_success_log(self, temp_log_dirs):
        _, cli_dir, _ = temp_log_dirs
        date_dir = cli_dir / "2026-06-26"
        date_dir.mkdir()
        log_file = date_dir / "100000_anthropic_claude-sonnet.log"
        log_file.write_text(
            _make_cli_log(exit_code=0, duration=5.0), encoding="utf-8"
        )

        entry = _parse_cli_log_file(log_file)

        assert entry is not None
        assert entry.source == "claude_cli"
        assert entry.level == "info"
        assert entry.metadata.provider == "anthropic"
        assert entry.metadata.model == "claude-sonnet"
        assert entry.metadata.exit_code == 0
        assert entry.metadata.duration_seconds == 5.0
        assert entry.metadata.route == "direct"
        assert "ok" in entry.summary
        assert entry.id.startswith("claude_cli:2026-06-26:100000")

    def test_parse_error_log(self, temp_log_dirs):
        _, cli_dir, _ = temp_log_dirs
        date_dir = cli_dir / "2026-06-26"
        date_dir.mkdir()
        log_file = date_dir / "100001_openai_gpt.log"
        log_file.write_text(
            _make_cli_log(
                exit_code=1,
                duration=180.0,
                stderr_text="timeout error",
                stdout_text="",
            ),
            encoding="utf-8",
        )

        entry = _parse_cli_log_file(log_file)

        assert entry is not None
        assert entry.level == "error"
        assert entry.metadata.exit_code == 1
        assert entry.metadata.duration_seconds == 180.0

    def test_parse_nonexistent_file(self, temp_log_dirs):
        _, cli_dir, _ = temp_log_dirs
        log_file = cli_dir / "nonexistent.log"
        assert _parse_cli_log_file(log_file) is None

    def test_entry_has_full_content(self, temp_log_dirs):
        _, cli_dir, _ = temp_log_dirs
        date_dir = cli_dir / "2026-06-26"
        date_dir.mkdir()
        content = _make_cli_log(stdout_text="hello world\n" * 10)
        log_file = date_dir / "test.log"
        log_file.write_text(content, encoding="utf-8")

        entry = _parse_cli_log_file(log_file)
        assert entry is not None
        assert entry.content == content
        # summary should be truncated to first 200 chars of stdout
        assert len(entry.summary) <= 200


class TestParseFailureAnalysisFile:
    def test_parse_report(self, temp_log_dirs):
        _, _, fa_dir = temp_log_dirs
        wf_dir = fa_dir / "Nightly-A2" / "test-job"
        wf_dir.mkdir(parents=True)
        report_file = wf_dir / "12345.md"
        report_file.write_text(
            "# Root Cause\n\nThe test timed out.\n",
            encoding="utf-8",
        )

        entry = _parse_failure_analysis_file(report_file)

        assert entry is not None
        assert entry.source == "failure_analysis"
        assert entry.level == "info"
        assert entry.metadata.workflow_name == "Nightly-A2"
        assert entry.metadata.job_name == "test-job"
        assert entry.metadata.job_id == 12345
        assert "Root Cause" in entry.summary
        assert "Root Cause" in entry.content

    def test_parse_nonexistent_file(self, temp_log_dirs):
        _, _, fa_dir = temp_log_dirs
        assert _parse_failure_analysis_file(fa_dir / "nonexistent.md") is None


# ============================================================================
# LogService.get_sources() Tests
# ============================================================================


class TestGetSources:
    @pytest.mark.asyncio
    async def test_returns_all_four_sources(self, db_with_app_logs):
        service = LogService()
        result = await service.get_sources(db_with_app_logs)

        keys = {s.key for s in result.sources}
        assert keys == {"claude_cli", "failure_analysis", "app", "scheduler"}

    @pytest.mark.asyncio
    async def test_counts_app_logs(self, db_with_app_logs):
        # Insert 3 app log entries
        for i in range(3):
            await db_with_app_logs.execute(
                text(
                    "INSERT INTO app_logs (timestamp, level, module, message) "
                    "VALUES (:ts, :level, :mod, :msg)"
                ),
                {
                    "ts": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
                    "level": "INFO",
                    "mod": f"test.module{i}",
                    "msg": f"test message {i}",
                },
            )
        await db_with_app_logs.commit()

        service = LogService()
        result = await service.get_sources(db_with_app_logs)

        app_src = next(s for s in result.sources if s.key == "app")
        assert app_src.count >= 3

    @pytest.mark.asyncio
    async def test_counts_scheduler_logs(self, db_with_app_logs):
        await db_with_app_logs.execute(
            text(
                "INSERT INTO app_logs (timestamp, level, module, message) "
                "VALUES (:ts, :level, :mod, :msg)"
            ),
            {
                "ts": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
                "level": "INFO",
                "mod": "app.services.scheduler",
                "msg": "Scheduler started",
            },
        )
        await db_with_app_logs.commit()

        service = LogService()
        result = await service.get_sources(db_with_app_logs)

        sched_src = next(s for s in result.sources if s.key == "scheduler")
        assert sched_src.count >= 1

    @pytest.mark.asyncio
    async def test_empty_db_returns_zero_counts(self, db_with_app_logs):
        service = LogService()
        result = await service.get_sources(db_with_app_logs)

        app_src = next(s for s in result.sources if s.key == "app")
        assert app_src.count == 0
        sched_src = next(s for s in result.sources if s.key == "scheduler")
        assert sched_src.count == 0

    @pytest.mark.asyncio
    async def test_counts_cli_logs(self, temp_log_dirs, db_with_app_logs):
        base, cli_dir, _ = temp_log_dirs
        # Create 2 CLI logs
        date_dir = cli_dir / "2026-06-26"
        date_dir.mkdir(parents=True)
        (date_dir / "a.log").write_text(
            _make_cli_log(), encoding="utf-8"
        )
        (date_dir / "b.log").write_text(
            _make_cli_log(), encoding="utf-8"
        )

        with patch(
            "app.services.log_service._CLI_LOG_DIR", cli_dir
        ):
            service = LogService()
            result = await service.get_sources(db_with_app_logs)

        cli_src = next(s for s in result.sources if s.key == "claude_cli")
        assert cli_src.count >= 2

    @pytest.mark.asyncio
    async def test_counts_failure_reports(
        self, temp_log_dirs, db_with_app_logs
    ):
        base, _, fa_dir = temp_log_dirs
        # Create 2 reports
        wf_dir = fa_dir / "nightly" / "job1"
        wf_dir.mkdir(parents=True)
        (wf_dir / "1.md").write_text("# report 1", encoding="utf-8")
        (wf_dir / "2.md").write_text("# report 2", encoding="utf-8")

        with patch(
            "app.services.log_service._FAILURE_ANALYSIS_DIR", fa_dir
        ):
            service = LogService()
            result = await service.get_sources(db_with_app_logs)

        fa_src = next(
            s for s in result.sources if s.key == "failure_analysis"
        )
        assert fa_src.count >= 2


# ============================================================================
# LogService.query() Tests
# ============================================================================


class TestQuery:
    @pytest.mark.asyncio
    async def test_query_app_logs_returns_entries(
        self, db_with_app_logs
    ):
        now = datetime.now(UTC)
        await db_with_app_logs.execute(
            text(
                "INSERT INTO app_logs "
                "(timestamp, level, module, message) "
                "VALUES (:ts, :level, :mod, :msg)"
            ),
            {
                "ts": now.strftime("%Y-%m-%d %H:%M:%S"),
                "level": "ERROR",
                "mod": "test.module",
                "msg": "Something went wrong",
            },
        )
        await db_with_app_logs.commit()

        service = LogService()
        filters = LogQueryRequest(page=1, page_size=10)
        result = await service.query(filters, db_with_app_logs)

        assert result.total >= 1
        assert len(result.entries) >= 1
        entry = result.entries[0]
        assert entry.source == "app"
        assert entry.level == "error"
        assert "Something went wrong" in entry.summary

    @pytest.mark.asyncio
    async def test_query_respects_source_filter(
        self, db_with_app_logs
    ):
        now = datetime.now(UTC)
        await db_with_app_logs.execute(
            text(
                "INSERT INTO app_logs "
                "(timestamp, level, module, message) "
                "VALUES (:ts, :level, :mod, :msg)"
            ),
            {
                "ts": now.strftime("%Y-%m-%d %H:%M:%S"),
                "level": "INFO",
                "mod": "test",
                "msg": "test",
            },
        )
        await db_with_app_logs.commit()

        service = LogService()
        # Query only claude_cli — should exclude app logs
        filters = LogQueryRequest(
            page=1, page_size=10, sources=["claude_cli"]
        )
        result = await service.query(filters, db_with_app_logs)

        app_entries = [
            e for e in result.entries if e.source == "app"
        ]
        assert len(app_entries) == 0

    @pytest.mark.asyncio
    async def test_query_respects_level_filter(
        self, db_with_app_logs
    ):
        now = datetime.now(UTC)
        for level, msg in [("ERROR", "err"), ("INFO", "info")]:
            await db_with_app_logs.execute(
                text(
                    "INSERT INTO app_logs "
                    "(timestamp, level, message) "
                    "VALUES (:ts, :level, :msg)"
                ),
                {
                    "ts": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "level": level,
                    "msg": msg,
                },
            )
        await db_with_app_logs.commit()

        service = LogService()
        filters = LogQueryRequest(
            page=1, page_size=10, levels=["error"]
        )
        result = await service.query(filters, db_with_app_logs)

        levels_in_result = {e.level for e in result.entries}
        assert "info" not in levels_in_result

    @pytest.mark.asyncio
    async def test_query_respects_search(self, db_with_app_logs):
        now = datetime.now(UTC)
        await db_with_app_logs.execute(
            text(
                "INSERT INTO app_logs "
                "(timestamp, level, message) "
                "VALUES (:ts, :level, :msg)"
            ),
            {
                "ts": now.strftime("%Y-%m-%d %H:%M:%S"),
                "level": "ERROR",
                "msg": "ConnectionTimeout: database unreachable",
            },
        )
        await db_with_app_logs.execute(
            text(
                "INSERT INTO app_logs "
                "(timestamp, level, message) "
                "VALUES (:ts, :level, :msg)"
            ),
            {
                "ts": now.strftime("%Y-%m-%d %H:%M:%S"),
                "level": "INFO",
                "msg": "Server started successfully",
            },
        )
        await db_with_app_logs.commit()

        service = LogService()
        filters = LogQueryRequest(
            page=1, page_size=10, search="ConnectionTimeout"
        )
        result = await service.query(filters, db_with_app_logs)

        assert result.total == 1
        assert "ConnectionTimeout" in result.entries[0].summary

    @pytest.mark.asyncio
    async def test_query_respects_time_range(
        self, db_with_app_logs
    ):
        now = datetime.now(UTC)
        one_hour_ago = now - timedelta(hours=1)

        # Old entry
        await db_with_app_logs.execute(
            text(
                "INSERT INTO app_logs (timestamp, level, message) "
                "VALUES (:ts, :level, :msg)"
            ),
            {
                "ts": one_hour_ago.strftime("%Y-%m-%d %H:%M:%S"),
                "level": "INFO",
                "msg": "old message",
            },
        )
        await db_with_app_logs.commit()

        service = LogService()
        filters = LogQueryRequest(
            page=1,
            page_size=10,
            time_range={
                "start": datetime.now(UTC) - timedelta(minutes=30),
                "end": datetime.now(UTC) + timedelta(minutes=10),
            },
        )
        result = await service.query(filters, db_with_app_logs)

        # The old entry (1 hour ago) should be excluded
        old_entries = [
            e for e in result.entries if "old message" in e.summary
        ]
        assert len(old_entries) == 0

    @pytest.mark.asyncio
    async def test_query_pagination(self, db_with_app_logs):
        now = datetime.now(UTC)
        for i in range(5):
            await db_with_app_logs.execute(
                text(
                    "INSERT INTO app_logs "
                    "(timestamp, level, message) "
                    "VALUES (:ts, :level, :msg)"
                ),
                {
                    "ts": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "level": "INFO",
                    "msg": f"message {i}",
                },
            )
        await db_with_app_logs.commit()

        service = LogService()

        # Page 1
        result1 = await service.query(
            LogQueryRequest(page=1, page_size=2), db_with_app_logs
        )
        assert len(result1.entries) <= 2
        assert result1.page == 1

        # Page 2
        result2 = await service.query(
            LogQueryRequest(page=2, page_size=2), db_with_app_logs
        )
        assert len(result2.entries) <= 2
        assert result2.page == 2

        # No overlap
        ids1 = {e.id for e in result1.entries}
        ids2 = {e.id for e in result2.entries}
        assert ids1.isdisjoint(ids2)

    @pytest.mark.asyncio
    async def test_query_entries_sorted_by_timestamp_desc(
        self, db_with_app_logs
    ):
        now = datetime.now(UTC)
        t1 = now - timedelta(minutes=10)
        t2 = now

        for ts, msg in [(t1, "older"), (t2, "newer")]:
            await db_with_app_logs.execute(
                text(
                    "INSERT INTO app_logs "
                    "(timestamp, level, message) "
                    "VALUES (:ts, :level, :msg)"
                ),
                {
                    "ts": ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "level": "INFO",
                    "msg": msg,
                },
            )
        await db_with_app_logs.commit()

        service = LogService()
        result = await service.query(
            LogQueryRequest(page=1, page_size=10), db_with_app_logs
        )

        app_entries = [
            e for e in result.entries if e.source == "app"
        ]
        assert len(app_entries) >= 2
        timestamps = [e.timestamp for e in app_entries]
        assert timestamps == sorted(timestamps, reverse=True)

    @pytest.mark.asyncio
    async def test_query_empty_result(self, db_with_app_logs):
        service = LogService()
        result = await service.query(
            LogQueryRequest(page=1, page_size=10), db_with_app_logs
        )
        assert isinstance(result.total, int)
        assert isinstance(result.entries, list)
        assert result.page == 1


# ============================================================================
# LogService.get_entry() Tests
# ============================================================================


class TestGetEntry:
    @pytest.mark.asyncio
    async def test_get_app_log_entry(self, db_with_app_logs):
        now = datetime.now(UTC)
        result = await db_with_app_logs.execute(
            text(
                "INSERT INTO app_logs "
                "(timestamp, level, module, message) "
                "VALUES (:ts, :level, :mod, :msg)"
            ),
            {
                "ts": now.strftime("%Y-%m-%d %H:%M:%S"),
                "level": "ERROR",
                "mod": "test.module",
                "msg": "test error",
            },
        )
        await db_with_app_logs.commit()
        row_id = result.lastrowid

        service = LogService()
        entry = await service.get_entry(
            f"app:{row_id}", db_with_app_logs
        )

        assert entry is not None
        assert entry.source == "app"
        assert entry.level == "error"
        assert "test error" in entry.content
        assert entry.metadata.module == "test.module"

    @pytest.mark.asyncio
    async def test_get_entry_not_found(self, db_with_app_logs):
        service = LogService()
        entry = await service.get_entry(
            "app:99999", db_with_app_logs
        )
        assert entry is None

    @pytest.mark.asyncio
    async def test_get_cli_entry(self, temp_log_dirs, db_with_app_logs):
        _, cli_dir, _ = temp_log_dirs
        date_dir = cli_dir / "2026-06-26"
        date_dir.mkdir()
        log_file = date_dir / "test_cli.log"
        log_file.write_text(_make_cli_log(), encoding="utf-8")

        with patch(
            "app.services.log_service._CLI_LOG_DIR", cli_dir
        ):
            service = LogService()
            entry = await service.get_entry(
                "claude_cli:2026-06-26:test_cli", db_with_app_logs
            )

        assert entry is not None
        assert entry.source == "claude_cli"
        assert entry.id == "claude_cli:2026-06-26:test_cli"

    @pytest.mark.asyncio
    async def test_get_failure_analysis_entry(
        self, temp_log_dirs, db_with_app_logs
    ):
        _, _, fa_dir = temp_log_dirs
        wf_dir = fa_dir / "nightly" / "job1"
        wf_dir.mkdir(parents=True)
        (wf_dir / "42.md").write_text("# Root cause", encoding="utf-8")

        with patch(
            "app.services.log_service._FAILURE_ANALYSIS_DIR", fa_dir
        ):
            service = LogService()
            entry = await service.get_entry(
                "failure_analysis:nightly:job1:42",
                db_with_app_logs,
            )

        assert entry is not None
        assert entry.source == "failure_analysis"
        assert entry.metadata.job_id == 42

    @pytest.mark.asyncio
    async def test_get_entry_invalid_id(self, db_with_app_logs):
        service = LogService()
        entry = await service.get_entry(
            "invalid", db_with_app_logs
        )
        assert entry is None


# ============================================================================
# DBLogHandler Tests
# ============================================================================


class TestDBLogHandler:
    def test_handler_emits_entry(self):
        """DBLogHandler should push an entry into the queue without errors."""
        from app.core.logging import DBLogHandler, _log_queue

        # Drain the queue first
        while not _log_queue.empty():
            try:
                _log_queue.get_nowait()
            except Exception:
                break

        handler = DBLogHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))

        logger = logging.getLogger("test.handler")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)

        logger.info("test message for db handler")

        logger.removeHandler(handler)

        # Queue should have at least one entry
        assert not _log_queue.empty()
        entry = _log_queue.get_nowait()
        assert entry["level"] == "INFO"
        assert entry["message"] == "test message for db handler"
        assert entry["module"] == "test.handler"
        assert entry["traceback"] is None

    def test_handler_captures_exception_traceback(self):
        from app.core.logging import DBLogHandler, _log_queue

        while not _log_queue.empty():
            try:
                _log_queue.get_nowait()
            except Exception:
                break

        handler = DBLogHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))

        logger = logging.getLogger("test.error")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)

        try:
            raise ValueError("something broke")
        except ValueError:
            logger.exception("An error occurred")

        logger.removeHandler(handler)

        assert not _log_queue.empty()
        entry = _log_queue.get_nowait()
        assert entry["level"] == "ERROR"
        assert "An error occurred" in entry["message"]
        assert entry["traceback"] is not None
        assert "ValueError" in entry["traceback"]

    def test_setup_db_logging_is_idempotent(self):
        """Calling setup_db_logging twice should not double-register."""
        from app.core.logging import setup_db_logging

        root_before = len(logging.getLogger().handlers)
        setup_db_logging()
        count_after_first = len(logging.getLogger().handlers)
        setup_db_logging()
        count_after_second = len(logging.getLogger().handlers)

        assert count_after_first == count_after_second


# ============================================================================
# API Endpoint Tests
# ============================================================================


@pytest.fixture
def test_client(db_with_app_logs):
    """Create a FastAPI TestClient patched to use our test DB."""
    from app.api.deps import get_db
    from app.main import app

    async def override_get_db():
        yield db_with_app_logs

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


class TestLogSourcesAPI:
    def test_returns_200(self, test_client):
        response = test_client.get("/api/v1/logs/sources")
        assert response.status_code == 200
        data = response.json()
        assert "sources" in data
        assert len(data["sources"]) == 4
        keys = {s["key"] for s in data["sources"]}
        assert keys == {
            "claude_cli",
            "failure_analysis",
            "app",
            "scheduler",
        }

    def test_source_has_required_fields(self, test_client):
        response = test_client.get("/api/v1/logs/sources")
        data = response.json()
        for source in data["sources"]:
            assert "key" in source
            assert "label" in source
            assert "count" in source
            assert "last_entry" in source


class TestLogQueryAPI:
    def test_returns_200_with_valid_body(self, test_client):
        response = test_client.post(
            "/api/v1/logs/query",
            json={"page": 1, "page_size": 10},
        )
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "entries" in data
        assert data["page"] == 1

    def test_returns_422_for_invalid_page_size(self, test_client):
        """page_size > 200 should be rejected."""
        response = test_client.post(
            "/api/v1/logs/query",
            json={"page": 1, "page_size": 999},
        )
        assert response.status_code == 422

class TestLogEntryAPI:
    def test_returns_404_for_nonexistent_entry(self, test_client):
        response = test_client.get(
            "/api/v1/logs/app:99999",
        )
        assert response.status_code == 404

    def test_entry_endpoint_accepts_encoded_id(self, test_client):
        """GET /logs/{id} with URL-encoded ID should return 404 for
        nonexistent (not 500). The endpoint itself is covered by
        TestGetEntry tests."""
        # URL-encoded ID with special chars
        response = test_client.get(
            "/api/v1/logs/claude_cli%3A2026-06-26%3Atest"
        )
        assert response.status_code == 404
