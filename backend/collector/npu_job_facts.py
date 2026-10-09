"""Normalization and idempotent persistence for GitHub NPU job facts.

The rules deliberately do not infer a pool from a display name or a hardware
string.  A label must match an explicit rule, otherwise the fact remains
``unmatched`` and is still available for audit/backfill.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence.models import CIJob, CINpuJobFact, CINpuSyncState, CIResult

_RULES_PATH = Path(__file__).resolve().parent.parent / "resources" / "npu_queue_label_rules.json"


@dataclass(frozen=True)
class NpuPoolRule:
    pattern: re.Pattern[str]
    pool: str
    accelerator_model: str
    cards: int | str


def _load_pool_rules() -> tuple[str, tuple[NpuPoolRule, ...]]:
    """Load the CI-owner supplied label rules; label matching is never fuzzy."""
    payload = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
    rules = tuple(
        NpuPoolRule(
            pattern=re.compile(str(item["match"]), re.IGNORECASE),
            pool=str(item["pool"]),
            accelerator_model=str(item["type"]),
            cards=item["cards"],
        )
        for item in payload["label_rules"]
    )
    return str(payload["rule_version"]), rules


RULE_VERSION, POOL_RULES = _load_pool_rules()


def parse_github_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def as_utc(value: datetime | None) -> datetime | None:
    """Normalize database and GitHub timestamps before comparing watermarks."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def label_names(job: dict[str, Any]) -> list[str]:
    values = job.get("labels") or []
    if not isinstance(values, list):
        return []
    return [str(value.get("name", "")) if isinstance(value, dict) else str(value) for value in values if value]


def map_pool(labels: list[str]) -> tuple[NpuPoolRule | None, str]:
    for label in labels:
        for rule in POOL_RULES:
            if rule.pattern.search(label):
                return rule, "matched"
    return None, "unmatched"


def extract_pr_number(run: dict[str, Any]) -> int | None:
    pull_requests = run.get("pull_requests")
    if not isinstance(pull_requests, list):
        return None
    for pull_request in pull_requests:
        if isinstance(pull_request, dict) and isinstance(pull_request.get("number"), int):
            return pull_request["number"]
    return None


def build_fact_values(
    job: dict[str, Any],
    run: dict[str, Any],
    *,
    repository: str,
    workflow_name: str,
) -> dict[str, Any]:
    labels = label_names(job)
    rule, mapping_status = map_pool(labels)
    queued_at = parse_github_timestamp(job.get("created_at"))
    started_at = parse_github_timestamp(job.get("started_at"))
    completed_at = parse_github_timestamp(job.get("completed_at"))
    quality = "ok" if queued_at else "missing_queued_at"
    source_updated_at = completed_at or started_at or queued_at
    job_id = int(job["id"])
    run_id = int(run.get("id") or job.get("run_id"))
    return {
        "job_id": job_id,
        "run_id": run_id,
        "repository": repository,
        "workflow_name": workflow_name,
        "job_name": str(job.get("name") or ""),
        "pr_number": extract_pr_number(run),
        "run_url": str(run.get("html_url") or "") or None,
        "job_url": str(job.get("html_url") or "") or None,
        "queued_at": queued_at,
        "queued_at_source": "github_job_created_at" if queued_at else "missing",
        "started_at": started_at,
        "completed_at": completed_at,
        "status": str(job.get("status") or "unknown"),
        "conclusion": job.get("conclusion"),
        "runner_labels": labels,
        "rule_version": RULE_VERSION,
        "pool": rule.pool if rule else None,
        "accelerator_model": rule.accelerator_model if rule else None,
        "mapped_cards": _mapped_cards(rule, labels),
        "mapping_status": mapping_status,
        "data_quality_status": quality,
        "source_updated_at": source_updated_at,
    }


def _mapped_cards(rule: NpuPoolRule | None, labels: list[str]) -> int | None:
    if rule is None:
        return None
    if isinstance(rule.cards, int):
        return rule.cards
    for label in labels:
        match = rule.pattern.search(label)
        if match and rule.cards == "g1":
            return int(match.group(1))
    return None


async def upsert_npu_job_fact(
    db: AsyncSession,
    job: dict[str, Any],
    run: dict[str, Any],
    *,
    repository: str,
    workflow_name: str,
) -> CINpuJobFact:
    values = build_fact_values(job, run, repository=repository, workflow_name=workflow_name)
    row = await db.scalar(select(CINpuJobFact).where(CINpuJobFact.job_id == values["job_id"]))
    if row is None:
        row = CINpuJobFact(**values)
        db.add(row)
    else:
        for field, value in values.items():
            setattr(row, field, value)
    return row


async def record_sync_success(
    db: AsyncSession,
    *,
    repository: str,
    job_id: int,
    watermark: datetime | None,
) -> None:
    # A backfill can call this repeatedly before the surrounding transaction
    # flushes.  Reuse the pending identity-map row instead of adding duplicate
    # repository rows that only collide at commit time.
    state = next(
        (
            row for row in db.new
            if isinstance(row, CINpuSyncState) and row.repository == repository
        ),
        None,
    )
    if state is None:
        state = await db.scalar(select(CINpuSyncState).where(CINpuSyncState.repository == repository))
    now = datetime.now(UTC)
    if state is None:
        state = CINpuSyncState(repository=repository)
        db.add(state)
    state.status = "ready"
    state.last_successful_sync = now
    state.last_job_id = job_id
    state.rule_version = RULE_VERSION
    normalized_watermark = as_utc(watermark)
    current_watermark = as_utc(state.successful_watermark)
    if normalized_watermark and (
        current_watermark is None or normalized_watermark > current_watermark
    ):
        state.successful_watermark = normalized_watermark


async def backfill_npu_job_facts(
    db: AsyncSession,
    *,
    repository: str,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 1_000,
) -> int:
    """Controlled, idempotent backfill for one repository/time slice.

    Callers own rate limiting and transaction boundaries.  This deliberately
    uses the already persisted GitHub payload instead of inventing timestamps
    from the dashboard's database ``created_at`` column.
    """
    statement = select(CIJob, CIResult).join(CIResult, CIResult.run_id == CIJob.run_id).order_by(CIJob.job_id).limit(limit)
    if start:
        statement = statement.where(CIJob.created_at >= start)
    if end:
        statement = statement.where(CIJob.created_at < end)
    count = 0
    for ci_job, ci_run in (await db.execute(statement)).all():
        try:
            job_payload = json.loads(ci_job.data or "{}")
            run_payload = json.loads(ci_run.data or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(job_payload, dict) or not isinstance(run_payload, dict) or not job_payload.get("id"):
            continue
        fact = await upsert_npu_job_fact(
            db,
            job_payload,
            run_payload,
            repository=repository,
            workflow_name=ci_job.workflow_name,
        )
        await record_sync_success(db, repository=repository, job_id=fact.job_id, watermark=fact.source_updated_at)
        count += 1
    return count
