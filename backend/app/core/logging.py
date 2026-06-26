"""
Database-backed logging handler.

Routes Python logging records into the app_logs table via a non-blocking
queue so that database writes never block the calling thread.
"""
import asyncio
import logging
import queue
import traceback
from datetime import UTC, datetime

from sqlalchemy import text

from app.db.base import SessionLocal

logger = logging.getLogger(__name__)

# Shared queue between the log handler (producer) and the DB worker (consumer).
_log_queue: queue.Queue = queue.Queue(maxsize=10000)

# Tracks whether setup_db_logging() has already been called.
_worker_started: bool = False


class DBLogHandler(logging.Handler):
    """Logging handler that inserts records into app_logs via a queue."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "timestamp": datetime.fromtimestamp(
                    record.created, tz=UTC
                ).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                "level": record.levelname,
                "module": record.name,
                "function_name": record.funcName,
                "line_number": record.lineno,
                "message": self.format(record),
                "traceback": (
                    traceback.format_exc() if record.exc_info else None
                ),
            }
            try:
                _log_queue.put_nowait(entry)
            except queue.Full:
                pass
        except Exception:
            self.handleError(record)


async def _db_log_worker() -> None:
    """Background worker: drain the queue and batch-insert into app_logs."""
    batch: list[dict] = []

    while True:
        try:
            entry = _log_queue.get(timeout=1)
            batch.append(entry)

            for _ in range(99):
                try:
                    entry = _log_queue.get_nowait()
                    batch.append(entry)
                except queue.Empty:
                    break

            if batch:
                await _flush_batch(batch)
                batch = []
        except queue.Empty:
            if batch:
                await _flush_batch(batch)
                batch = []
        except Exception as e:
            logger.warning("DB log worker error: %s", e)
            await asyncio.sleep(1)


async def _flush_batch(entries: list[dict]) -> None:
    """Insert a batch of log entries into app_logs."""
    if not entries:
        return
    async with SessionLocal() as db:
        try:
            for entry in entries:
                await db.execute(
                    text(
                        "INSERT INTO app_logs "
                        "(timestamp, level, module, function_name, "
                        "line_number, message, traceback) "
                        "VALUES "
                        "(:timestamp, :level, :module, :function_name, "
                        ":line_number, :message, :traceback)"
                    ),
                    entry,
                )
            await db.commit()
        except Exception:
            await db.rollback()
            raise


def setup_db_logging() -> None:
    """Install the DB log handler and start the background worker.

    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _worker_started
    if _worker_started:
        return
    _worker_started = True

    handler = DBLogHandler()
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(message)s"))

    root = logging.getLogger()
    root.addHandler(handler)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_db_log_worker())
        logger.info("DB log handler started")
    except RuntimeError:
        # No running event loop — worker will not start until one exists.
        # In practice setup_db_logging() is called during lifespan startup
        # when the event loop is already running.
        pass
