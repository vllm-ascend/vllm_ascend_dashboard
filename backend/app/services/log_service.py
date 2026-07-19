"""
Log Service — multi-source log aggregation, search, and pagination.

Sources:
  - claude_cli:       file system logs under data/claude_logs/
  - failure_analysis: file system reports under data/failure-analysis/
  - app / scheduler:  MySQL app_logs table
"""
import logging
import os
import re
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import text

from app.core.config import settings
from app.schemas.logs import (
    LogEntryMetadata,
    LogEntryResponse,
    LogQueryRequest,
    LogQueryResponse,
    LogSourceInfo,
    LogSourcesResponse,
)

logger = logging.getLogger(__name__)

_CLI_LOG_DIR = Path(settings.DATA_DIR) / "claude_logs"
_FAILURE_ANALYSIS_DIR = Path(settings.DATA_DIR) / "failure-analysis"


def _to_utc_datetime(value) -> datetime:
    """Convert a DB timestamp value (str or datetime) to tz-aware UTC."""
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            for fmt in (
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S",
            ):
                try:
                    dt = datetime.strptime(value, fmt)
                    break
                except ValueError:
                    continue
            else:
                return datetime.now(timezone.utc)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# File parsers
# ---------------------------------------------------------------------------


def _parse_cli_log_file(filepath: Path) -> Optional[LogEntryResponse]:
    """Parse a Claude Code CLI log file (.log or _conversation.json) into a LogEntryResponse."""
    is_conversation = filepath.name.endswith("_conversation.json")

    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception:
        return None

    # conversation.json：从 JSON 提取轮次摘要
    conversation_content = ""
    if is_conversation:
        try:
            import json
            conv_data = json.loads(content)
            provider = "openai"  # conversation.json 不存储 provider
            model = conv_data.get("model", "")
            turns = conv_data.get("conversation", [])
            if turns:
                lines = [f"总轮数: {len(turns)} | 模型: {model}"]
                for t in turns:
                    tn = t.get("turn", "?")
                    resp = t.get("response", {})
                    choices = resp.get("choices", [])
                    elapsed = t.get("elapsed_ms", 0)
                    usage = resp.get("usage", {})
                    tok_info = f"in={usage.get('prompt_tokens','?')} out={usage.get('completion_tokens','?')}" if usage else ""
                    is_tool = all(c.get("content", "") == "" for c in choices)
                    lines.append(f"\n{'='*60}")
                    lines.append(f"[轮次 {tn}] {elapsed}ms {tok_info}")
                    if is_tool:
                        lines.append("  (工具调用)")
                        for m in t.get("request", {}).get("messages", []):
                            for tc in m.get("tool_calls", []):
                                args = tc.get("args", "")
                                lines.append(f"  → {tc.get('name', '?')}: {args[:500]}")
                    else:
                        for c in choices:
                            if c.get("content"):
                                lines.append(f"  {c['content'][:2000]}")
                                break
                conversation_content = "\n".join(lines)
            duration = 0
            exit_code = 0
            summary = f"Conversation: {len(turns)} turns"
            stat = filepath.stat()
            timestamp = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            date_str = filepath.parent.name
            file_id = filepath.stem.replace("_conversation", "")
            return LogEntryResponse(
                id=f"claude_cli:{date_str}:{file_id}",
                source="claude_cli",
                level="info",
                timestamp=timestamp,
                summary=summary,
                content=conversation_content,
                metadata=LogEntryMetadata(provider=provider, model=model, duration_seconds=duration, exit_code=exit_code),
            )
        except Exception:
            return None

    provider = ""
    model = ""
    route = ""
    duration = 0.0
    exit_code = 0

    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("Provider:"):
            provider = line.split(":", 1)[1].strip()
        elif line.startswith("Model:"):
            model = line.split(":", 1)[1].strip()
        elif line.startswith("Route:"):
            route = line.split(":", 1)[1].strip()
        elif line.startswith("Duration:"):
            try:
                duration = float(line.split(":", 1)[1].strip().rstrip("s"))
            except ValueError:
                pass
        elif line.startswith("Exit Code:"):
            try:
                exit_code = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass

    level = "error" if exit_code != 0 else "info"

    # Summary: first 200 chars of STDOUT section
    summary = ""
    stdout_start = content.find("--- STDOUT ---")
    if stdout_start != -1:
        stdout_text = content[stdout_start + 15:]
        stderr_start = stdout_text.find("--- STDERR ---")
        if stderr_start != -1:
            stdout_text = stdout_text[:stderr_start]
        summary = stdout_text.strip()[:200]

    # 尝试加载 conversation.json 获取轮次详情
    conversation_content = ""
    conv_path = filepath.parent / filepath.name.replace(".log", "_conversation.json")
    if conv_path.exists():
        try:
            import json
            conv_data = json.loads(conv_path.read_text(encoding="utf-8"))
            turns = conv_data.get("conversation", [])
            if turns:
                lines = [f"总轮数: {len(turns)}"]
                for t in turns:
                    tn = t.get("turn", "?")
                    resp = t.get("response", {})
                    choices = resp.get("choices", [])
                    elapsed = t.get("elapsed_ms", 0)
                    is_tool = all(c.get("content", "") == "" for c in choices)
                    if is_tool:
                        lines.append(f"\n[轮次 {tn}] (工具调用, {elapsed}ms)")
                        # 列出 tool calls
                        for m in t.get("request", {}).get("messages", []):
                            for tc in m.get("tool_calls", []):
                                lines.append(f"  → {tc.get('name', '?')}: {tc.get('args', '')[:200]}")
                    else:
                        content_preview = ""
                        for c in choices:
                            if c.get("content"):
                                content_preview = c["content"][:300]
                                break
                        lines.append(f"\n[轮次 {tn}] ({elapsed}ms): {content_preview}")
                conversation_content = "\n".join(lines)
        except Exception:
            pass

    stat = filepath.stat()
    timestamp = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

    date_str = filepath.parent.name  # YYYY-MM-DD
    file_id = filepath.stem
    log_id = f"claude_cli:{date_str}:{file_id}"

    return LogEntryResponse(
        id=log_id,
        source="claude_cli",
        level=level,
        timestamp=timestamp,
        summary=summary,
        content=conversation_content if conversation_content else content,
        metadata=LogEntryMetadata(
            provider=provider,
            model=model,
            duration_seconds=duration,
            exit_code=exit_code,
            route=route,
        ),
    )


def _parse_failure_analysis_file(
    filepath: Path,
) -> Optional[LogEntryResponse]:
    """Parse a failure analysis report into a LogEntryResponse."""
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception:
        return None

    # Path: failure-analysis/<workflow>/<job>/<job_id>.md
    parts = filepath.parts
    try:
        idx = parts.index("failure-analysis")
        workflow_name = parts[idx + 1] if len(parts) > idx + 1 else ""
        job_name = parts[idx + 2] if len(parts) > idx + 2 else ""
        job_id_str = filepath.stem
    except (ValueError, IndexError):
        workflow_name = ""
        job_name = ""
        job_id_str = ""

    stat = filepath.stat()
    timestamp = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

    summary = content[:200].replace("\n", " ")
    log_id = f"failure_analysis:{workflow_name}:{job_name}:{job_id_str}"

    return LogEntryResponse(
        id=log_id,
        source="failure_analysis",
        level="info",
        timestamp=timestamp,
        summary=summary,
        content=content,
        metadata=LogEntryMetadata(
            workflow_name=workflow_name,
            job_name=job_name,
            job_id=int(job_id_str) if job_id_str.isdigit() else None,
            analysis_status="completed",
        ),
    )


# ---------------------------------------------------------------------------
# LogService
# ---------------------------------------------------------------------------


class LogService:
    """Multi-source log query service."""

    async def get_sources(self, db) -> LogSourcesResponse:
        """Return available log sources with entry counts."""
        sources: list[LogSourceInfo] = []

        # claude_cli
        cli_count = 0
        cli_last: Optional[datetime] = None
        if _CLI_LOG_DIR.exists():
            for date_dir in _CLI_LOG_DIR.iterdir():
                if date_dir.is_dir():
                    for log_file in date_dir.iterdir():
                        if log_file.suffix == ".log":
                            cli_count += 1
                            mtime = datetime.fromtimestamp(
                                log_file.stat().st_mtime,
                                tz=timezone.utc,
                            )
                            if cli_last is None or mtime > cli_last:
                                cli_last = mtime
        sources.append(
            LogSourceInfo(
                key="claude_cli",
                label="Claude CLI",
                count=cli_count,
                last_entry=cli_last,
            )
        )

        # failure_analysis
        fa_count = 0
        fa_last: Optional[datetime] = None
        if _FAILURE_ANALYSIS_DIR.exists():
            for root, _dirs, files in os.walk(_FAILURE_ANALYSIS_DIR):
                for f in files:
                    if f.endswith(".md"):
                        fa_count += 1
                        fp = Path(root) / f
                        mtime = datetime.fromtimestamp(
                            fp.stat().st_mtime, tz=timezone.utc
                        )
                        if fa_last is None or mtime > fa_last:
                            fa_last = mtime
        sources.append(
            LogSourceInfo(
                key="failure_analysis",
                label="失败分析",
                count=fa_count,
                last_entry=fa_last,
            )
        )

        # app / scheduler from DB
        for src_key, src_label, mod_filter in [
            ("app", "应用日志", None),
            ("scheduler", "调度器", "%scheduler%"),
        ]:
            try:
                where = ""
                params = {}
                if mod_filter:
                    where = " WHERE module LIKE :mod"
                    params = {"mod": mod_filter}
                else:
                    where = " WHERE (module IS NULL OR module NOT LIKE :mod)"
                    params = {"mod": "%scheduler%"}

                result = await db.execute(
                    text(
                        f"SELECT COUNT(*) as cnt, MAX(timestamp) as last_ts "
                        f"FROM app_logs{where}"
                    ),
                    params,
                )
                row = result.fetchone()
                sources.append(
                    LogSourceInfo(
                        key=src_key,
                        label=src_label,
                        count=row.cnt if row and row.cnt else 0,
                        last_entry=row.last_ts if row and row.last_ts else None,
                    )
                )
            except Exception as e:
                logger.warning("Failed to count %s logs: %s", src_key, e)
                sources.append(
                    LogSourceInfo(
                        key=src_key,
                        label=src_label,
                        count=0,
                        last_entry=None,
                    )
                )

        return LogSourcesResponse(sources=sources)

    async def query(
        self, filters: LogQueryRequest, db
    ) -> LogQueryResponse:
        """Query logs across all sources with filtering and pagination."""
        entries: list[LogEntryResponse] = []

        active_sources = filters.sources or [
            "claude_cli",
            "failure_analysis",
            "app",
            "scheduler",
        ]
        active_levels = filters.levels or [
            "debug",
            "info",
            "warning",
            "error",
        ]

        if "claude_cli" in active_sources:
            entries.extend(
                self._query_cli_logs(filters, active_levels)
            )

        if "failure_analysis" in active_sources:
            entries.extend(
                self._query_failure_analysis(filters, active_levels)
            )

        if "app" in active_sources or "scheduler" in active_sources:
            db_entries = await self._query_app_logs(
                filters, active_sources, active_levels, db
            )
            entries.extend(db_entries)

        # Sort descending by timestamp
        entries.sort(key=lambda e: e.timestamp, reverse=True)

        # Apply search filter for file-based sources (DB already filtered)
        if filters.search:
            search_lower = filters.search.lower()
            entries = [
                e
                for e in entries
                if search_lower in e.summary.lower()
                or search_lower in e.content.lower()
            ]

        # Paginate
        total = len(entries)
        start = (filters.page - 1) * filters.page_size
        end = start + filters.page_size
        page_entries = entries[start:end]

        return LogQueryResponse(
            total=total,
            page=filters.page,
            page_size=filters.page_size,
            entries=page_entries,
        )

    async def get_entry(
        self, log_id: str, db
    ) -> Optional[LogEntryResponse]:
        """Get a single log entry by ID."""
        parts = log_id.split(":", 1)
        if len(parts) < 2:
            return None
        source = parts[0]

        if source == "claude_cli":
            try:
                date, filename = parts[1].split(":", 1)
                # 先查 .log，再查 _conversation.json
                log_path = _CLI_LOG_DIR / date / f"{filename}.log"
                conv_path = _CLI_LOG_DIR / date / f"{filename}_conversation.json"
                if log_path.exists():
                    return _parse_cli_log_file(log_path)
                if conv_path.exists():
                    return _parse_cli_log_file(conv_path)
            except ValueError:
                return None

        elif source == "failure_analysis":
            try:
                _, workflow, job, job_id_str = log_id.split(":", 3)
                filepath = (
                    _FAILURE_ANALYSIS_DIR
                    / workflow
                    / job
                    / f"{job_id_str}.md"
                )
                if filepath.exists():
                    return _parse_failure_analysis_file(filepath)
            except ValueError:
                return None

        elif source in ("app", "scheduler"):
            try:
                db_id = int(parts[1])
                result = await db.execute(
                    text(
                        "SELECT id, timestamp, level, module, "
                        "function_name, line_number, message, traceback "
                        "FROM app_logs WHERE id = :id"
                    ),
                    {"id": db_id},
                )
                row = result.fetchone()
                if row:
                    is_scheduler = (
                        row.module
                        and "scheduler" in row.module.lower()
                    )
                    return LogEntryResponse(
                        id=log_id,
                        source="scheduler" if is_scheduler else "app",
                        level=(
                            row.level.lower()
                            if row.level
                            else "info"
                        ),
                        timestamp=_to_utc_datetime(row.timestamp),
                        summary=(row.message or "")[:200],
                        content=(
                            (row.message or "")
                            + (
                                "\n\n--- TRACEBACK ---\n" + row.traceback
                                if row.traceback
                                else ""
                            )
                        ),
                        metadata=LogEntryMetadata(
                            module=row.module,
                            function_name=row.function_name,
                            line_number=row.line_number,
                        ),
                    )
            except Exception as e:
                logger.warning("Failed to get app log %s: %s", log_id, e)

        return None

    # ---- Private helpers ------------------------------------------------

    def _query_cli_logs(
        self, filters: LogQueryRequest, levels: list[str]
    ) -> list[LogEntryResponse]:
        entries: list[LogEntryResponse] = []
        if not _CLI_LOG_DIR.exists():
            return entries

        processed: set[str] = set()  # 已处理的文件 stem，避免重复
        for date_dir in sorted(_CLI_LOG_DIR.iterdir(), reverse=True):
            if not date_dir.is_dir():
                continue
            # 先收集所有文件 stem
            stems: dict[str, dict[str, Path]] = {}
            for f in date_dir.iterdir():
                stem = f.name.replace(".log", "").replace("_conversation.json", "")
                if stem not in stems:
                    stems[stem] = {}
                if f.suffix == ".log":
                    stems[stem]["log"] = f
                elif f.name.endswith("_conversation.json"):
                    stems[stem]["conv"] = f

            for stem, files in sorted(stems.items(), key=lambda x: x[0], reverse=True):
                if stem in processed:
                    continue
                processed.add(stem)
                # 优先用 .log 文件（含 metadata），其次用 conversation.json
                log_file = files.get("log") or files.get("conv")
                if log_file is None:
                    continue
                entry = _parse_cli_log_file(log_file)
                if entry is None:
                    continue
                if entry.level not in levels:
                    continue
                if not self._in_time_range(entry.timestamp, filters):
                    continue
                entries.append(entry)
        return entries

    def _query_failure_analysis(
        self, filters: LogQueryRequest, levels: list[str]
    ) -> list[LogEntryResponse]:
        entries: list[LogEntryResponse] = []
        if not _FAILURE_ANALYSIS_DIR.exists():
            return entries

        for root, _dirs, files in os.walk(_FAILURE_ANALYSIS_DIR):
            for f in files:
                if not f.endswith(".md"):
                    continue
                fp = Path(root) / f
                entry = _parse_failure_analysis_file(fp)
                if entry is None:
                    continue
                if entry.level not in levels:
                    continue
                if not self._in_time_range(entry.timestamp, filters):
                    continue
                entries.append(entry)
        return entries

    async def _query_app_logs(
        self,
        filters: LogQueryRequest,
        sources: list[str],
        levels: list[str],
        db,
    ) -> list[LogEntryResponse]:
        entries: list[LogEntryResponse] = []
        conditions: list[str] = []
        params: dict = {}

        # Source filter
        if "app" not in sources:
            conditions.append("module LIKE :sched_mod")
            params["sched_mod"] = "%scheduler%"
        elif "scheduler" not in sources:
            conditions.append(
                "(module IS NULL OR module NOT LIKE :not_sched)"
            )
            params["not_sched"] = "%scheduler%"

        # Level filter
        if levels and len(levels) < 4:
            level_clauses = []
            for i, lvl in enumerate(levels):
                key = f"level_{i}"
                level_clauses.append(f":{key}")
                params[key] = lvl.upper()
            conditions.append(
                f"level IN ({', '.join(level_clauses)})"
            )

        # Time range
        if filters.time_range and filters.time_range.start:
            conditions.append("timestamp >= :ts_start")
            params["ts_start"] = filters.time_range.start
        if filters.time_range and filters.time_range.end:
            conditions.append("timestamp <= :ts_end")
            params["ts_end"] = filters.time_range.end

        # Search
        if filters.search:
            conditions.append(
                "message LIKE :search_like"
            )
            params["search_like"] = f"%{filters.search}%"

        where_clause = ""
        if conditions:
            where_clause = " WHERE " + " AND ".join(conditions)

        query_sql = (
            "SELECT id, timestamp, level, module, "
            "function_name, line_number, message, traceback "
            f"FROM app_logs{where_clause} "
            "ORDER BY timestamp DESC "
            "LIMIT :limit OFFSET :offset"
        )
        params["limit"] = filters.page_size * 3
        params["offset"] = 0

        try:
            result = await db.execute(text(query_sql), params)
            rows = result.fetchall()
            for row in rows:
                is_scheduler = (
                    row.module and "scheduler" in row.module.lower()
                )
                source = "scheduler" if is_scheduler else "app"
                entries.append(
                    LogEntryResponse(
                        id=f"{source}:{row.id}",
                        source=source,
                        level=(
                            row.level.lower()
                            if row.level
                            else "info"
                        ),
                        timestamp=_to_utc_datetime(row.timestamp),
                        summary=(row.message or "")[:200],
                        content=(
                            (row.message or "")
                            + (
                                "\n\n--- TRACEBACK ---\n" + row.traceback
                                if row.traceback
                                else ""
                            )
                        ),
                        metadata=LogEntryMetadata(
                            module=row.module,
                            function_name=row.function_name,
                            line_number=row.line_number,
                        ),
                    )
                )
        except Exception as e:
            logger.error("Failed to query app_logs: %s", e)

        return entries

    @staticmethod
    def _in_time_range(
        ts: datetime, filters: LogQueryRequest
    ) -> bool:
        if not filters.time_range:
            return True
        if filters.time_range.start and ts < filters.time_range.start:
            return False
        if filters.time_range.end and ts > filters.time_range.end:
            return False
        return True
