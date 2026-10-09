"""Aggregate normalized CI NPU job facts for the dashboard read API."""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from math import ceil
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.persistence.models import CINpuJobFact


def _minutes(start: datetime | None, end: datetime | None) -> float | None:
    if not start or not end:
        return None
    return max((end - start).total_seconds() / 60, 0)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 1)


def _is_waiting(fact: CINpuJobFact) -> bool:
    return fact.status == "queued" or (fact.started_at == fact.queued_at and fact.completed_at is None)


def _is_running(fact: CINpuJobFact) -> bool:
    return fact.started_at is not None and fact.completed_at is None and not _is_waiting(fact)


def _queue_minutes(fact: CINpuJobFact) -> float | None:
    if not fact.queued_at or not fact.started_at or fact.started_at <= fact.queued_at:
        return None
    return _minutes(fact.queued_at, fact.started_at)


async def build_dashboard(db: AsyncSession) -> dict[str, Any]:
    facts = list((await db.scalars(select(CINpuJobFact).order_by(CINpuJobFact.queued_at.desc()))).all())
    now = datetime.now(UTC)
    matched = [fact for fact in facts if fact.mapping_status == "matched" and fact.mapped_cards]
    pools: dict[str, list[CINpuJobFact]] = defaultdict(list)
    for fact in matched:
        pools[fact.pool or "未映射资源池"].append(fact)

    pool_rows = []
    all_waiting: list[CINpuJobFact] = []
    all_running: list[CINpuJobFact] = []
    queue_samples: list[float] = []
    for name, rows in pools.items():
        waiting = [row for row in rows if _is_waiting(row)]
        running = [row for row in rows if _is_running(row)]
        samples = [value for row in rows if (value := _queue_minutes(row)) is not None and value >= 2]
        all_waiting.extend(waiting)
        all_running.extend(running)
        queue_samples.extend(samples)
        pool_rows.append({
            "key": name,
            "name": name,
            "capacity": None,
            "waitingJobs": len(waiting),
            "waitingCards": sum(row.mapped_cards or 0 for row in waiting),
            "runningJobs": len(running),
            "runningCards": sum(row.mapped_cards or 0 for row in running),
            "todayCardHours": 0,
            "queueP50": _percentile(samples, .5),
            "queueP90": _percentile(samples, .9),
            "samples": len(samples),
            "physicalRunningCards": None,
            "collectedAt": now.isoformat(),
        })

    queue_rows = []
    for fact in sorted(all_waiting, key=lambda row: row.queued_at or now):
        wait = _minutes(fact.queued_at, now) or 0
        queue_rows.append({
            "key": str(fact.job_id), "waitMinutes": round(wait), "run": f"#{fact.run_id}",
            "title": fact.job_name or "", "job": fact.job_name or "", "pool": fact.pool or "未映射",
            "cards": fact.mapped_cards or 0, "createdAt": fact.queued_at.isoformat() if fact.queued_at else "—",
            "state": "short" if wait < 2 else "waiting",
        })

    point = {
        "timestamp": now.strftime("%H:%M"),
        "waitingCards": sum(row.mapped_cards or 0 for row in all_waiting),
        "runningCards": sum(row.mapped_cards or 0 for row in all_running),
        "waitingJobs": len(all_waiting), "runningJobs": len(all_running),
    }
    daily_queue: dict[str, list[float]] = defaultdict(list)
    daily_usage: dict[str, dict[str, float]] = defaultdict(lambda: {"cardHours": 0, "jobs": 0, "failedCardHours": 0})
    pr_costs: dict[str, dict[str, Any]] = {}
    for fact in matched:
        queue_minutes = _queue_minutes(fact)
        if queue_minutes is not None and queue_minutes >= 2 and fact.started_at:
            daily_queue[fact.started_at.date().isoformat()].append(queue_minutes)
        runtime_minutes = _minutes(fact.started_at, fact.completed_at)
        if runtime_minutes is None or not fact.completed_at:
            continue
        card_hours = runtime_minutes * (fact.mapped_cards or 0) / 60
        day = fact.completed_at.date().isoformat()
        daily_usage[day]["cardHours"] += card_hours
        daily_usage[day]["jobs"] += 1
        if fact.conclusion != "success":
            daily_usage[day]["failedCardHours"] += card_hours
        key = f"pr-{fact.pr_number}" if fact.pr_number else f"run-{fact.run_id}"
        cost = pr_costs.setdefault(key, {"key": key, "title": fact.job_name or key, "branch": key, "cardHours": 0.0, "allCardHours": 0.0, "runs": set(), "successfulRuns": set()})
        cost["allCardHours"] += card_hours
        cost["runs"].add(fact.run_id)
        if fact.conclusion == "success":
            cost["cardHours"] += card_hours
            cost["successfulRuns"].add(fact.run_id)

    daily_queue_rows = [{"date": day, "p50": _percentile(values, .5), "p90": _percentile(values, .9), "samples": len(values), "abandoned": 0} for day, values in sorted(daily_queue.items())]
    daily_usage_rows = [{"date": day, "cardHours": round(values["cardHours"], 2), "jobs": int(values["jobs"]), "failedCardHours": round(values["failedCardHours"], 2)} for day, values in sorted(daily_usage.items())]
    pr_cost_rows = [{**cost, "cardHours": round(cost["cardHours"], 2), "allCardHours": round(cost["allCardHours"], 2), "runs": len(cost["runs"]), "successfulRuns": len(cost["successfulRuns"])} for cost in pr_costs.values()]
    return {
        "generatedAt": now.isoformat(), "pools": sorted(pool_rows, key=lambda row: row["name"]),
        "trend": [point], "dailyQueue": daily_queue_rows, "dailyUsage": daily_usage_rows, "queue": queue_rows,
        "prCosts": sorted(pr_cost_rows, key=lambda row: row["allCardHours"], reverse=True)[:15],
        "dataQuality": {"matched_jobs": len(matched), "unmatched_jobs": len(facts) - len(matched)},
    }
