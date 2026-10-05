"""Optional workflow-run selection rules for CI collection."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta, timezone
from functools import lru_cache

logger = logging.getLogger(__name__)
BEIJING_TZ = timezone(timedelta(hours=8))


def hour_in_window(local_hour: int, start_hour: int, end_hour: int) -> bool:
    """Check a Beijing-time hour against an end-exclusive, possibly overnight window."""
    if not 0 <= start_hour <= 23 or not 0 <= end_hour <= 23:
        logger.warning("Ignoring invalid workflow time window: %s-%s", start_hour, end_hour)
        return True
    if start_hour > end_hour:
        return local_hour >= start_hour or local_hour < end_hour
    if start_hour < end_hour:
        return start_hour <= local_hour < end_hour
    return True


@lru_cache(maxsize=256)
def compile_name_regex(pattern: str) -> re.Pattern[str] | None:
    """Invalid configured expressions fail closed rather than collecting every run."""
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        logger.error("Invalid workflow name regex %r: %s", pattern, exc)
        return None


def matches_workflow_policy(
    started_at: datetime | None,
    raw_name: str,
    start_hour: int | None,
    end_hour: int | None,
    name_regex: str | None,
) -> bool:
    """Apply optional time and raw GitHub name conditions before persistence."""
    if start_hour is not None and end_hour is not None:
        if started_at is None:
            return False
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        if not hour_in_window(started_at.astimezone(BEIJING_TZ).hour, start_hour, end_hour):
            return False

    if name_regex and name_regex.strip():
        matcher = compile_name_regex(name_regex.strip())
        if matcher is None or matcher.search(raw_name) is None:
            return False
    return True
