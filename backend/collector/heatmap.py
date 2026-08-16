"""Collector-side GitHub heatmap synchronization."""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from infrastructure.persistence.models import CodeMetricsFileHeatmap, PullRequest


async def sync_heatmap_from_github(
    db,
    github_client,
    owner: str,
    repo: str,
    days: int = 30,
) -> dict:
    """Aggregate PR file changes and persist the heatmap from the execution role."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    result = await db.execute(
        select(PullRequest.pr_number, PullRequest.title)
        .where(
            PullRequest.owner == owner,
            PullRequest.repo == repo,
            PullRequest.created_at >= cutoff,
        )
        .order_by(PullRequest.created_at.desc())
        .limit(100)
    )
    file_changes: Counter = Counter()
    file_bug_fixes: Counter = Counter()
    bug_keywords = ["fix", "bug", "error", "crash", "fail", "issue", "patch"]

    for pr_number, title in result:
        is_bug_fix = any(keyword in (title or "").lower() for keyword in bug_keywords)
        for item in await github_client.get_pr_files(owner, repo, pr_number):
            path = item.get("filename", "") if isinstance(item, dict) else ""
            if path:
                file_changes[path] += 1
                if is_bug_fix:
                    file_bug_fixes[path] += 1

    updated = 0
    for path, count in file_changes.most_common(500):
        record = (
            await db.execute(
                select(CodeMetricsFileHeatmap).where(
                    CodeMetricsFileHeatmap.repo == "vllm-ascend",
                    CodeMetricsFileHeatmap.file_path == path,
                )
            )
        ).scalar_one_or_none()
        if record:
            record.change_count = count
            record.bug_fix_count = file_bug_fixes.get(path, 0)
            record.last_changed = datetime.now(UTC)
        else:
            db.add(
                CodeMetricsFileHeatmap(
                    repo="vllm-ascend",
                    file_path=path,
                    change_count=count,
                    bug_fix_count=file_bug_fixes.get(path, 0),
                    last_changed=datetime.now(UTC),
                )
            )
        updated += 1
    await db.commit()
    return {"updated": updated, "total_files": len(file_changes)}
