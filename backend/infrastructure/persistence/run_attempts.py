"""Helpers for handling GitHub workflow re-runs.

GitHub keeps the same workflow ``run_id`` when a run is re-run, but the jobs
returned by the API belong to different ``run_attempt`` values. Persisted
jobs from an earlier attempt must not be presented as part of the final run.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any


def extract_run_attempt(payload: str | dict[str, Any] | None) -> int | None:
    """Return the GitHub ``run_attempt`` in a stored API payload."""

    if payload is None:
        return None
    value: Any = payload
    if isinstance(payload, str):
        try:
            value = json.loads(payload)
        except (TypeError, ValueError):
            return None
    if not isinstance(value, dict):
        return None
    attempt = value.get("run_attempt")
    try:
        return int(attempt) if attempt is not None else None
    except (TypeError, ValueError):
        return None


def is_current_run_attempt(
    job_payload: str | dict[str, Any] | None,
    current_attempt: int | None,
) -> bool:
    """Whether a job belongs to the current workflow attempt.

    Unknown values are retained for backwards compatibility with rows written
    before ``run_attempt`` was persisted. If the workflow attempt itself is
    unknown, no filtering is possible and every job is retained.
    """

    if current_attempt is None:
        return True
    job_attempt = extract_run_attempt(job_payload)
    return job_attempt is None or job_attempt == current_attempt


def _job_payload(job: Any) -> str | dict[str, Any] | None:
    if isinstance(job, dict):
        return job.get("data")
    return getattr(job, "data", None)


def filter_current_run_attempt(
    jobs: Iterable[Any],
    current_attempt: int | None,
) -> list[Any]:
    """Filter jobs to the final GitHub workflow attempt.

    If no payload has a matching attempt (for example, a legacy/mock response),
    return the original list instead of accidentally hiding all jobs.
    """

    jobs_list = list(jobs)
    if current_attempt is None:
        return jobs_list

    matching = [
        job for job in jobs_list if extract_run_attempt(_job_payload(job)) == current_attempt
    ]
    unknown = [job for job in jobs_list if extract_run_attempt(_job_payload(job)) is None]
    return matching + unknown if matching else jobs_list
