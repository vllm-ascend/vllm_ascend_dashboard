"""Render a saved daily-report draft through the exact delivery code path.

This script intentionally does not regenerate aggregate data or synthesize report
Markdown.  A useful preview must use the same persisted snapshot and AI content
that ``send_draft`` will deliver.
"""
import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.base import SessionLocal, engine
from app.models import DailyReportHistory
from app.services.daily_report import DailyReportService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview the exact saved daily-report draft/email."
    )
    parser.add_argument(
        "--report-id",
        type=int,
        help="Saved daily_report_history ID; defaults to the latest exact snapshot.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "real_daily_report_preview.html",
        help="HTML output path.",
    )
    return parser.parse_args()


def _has_exact_snapshot(history: DailyReportHistory) -> bool:
    performance = history.performance_summary
    return (
        bool(history.ai_report_content)
        and isinstance(performance, dict)
        and isinstance(performance.get("_report_snapshot"), dict)
    )


async def _load_history(db, report_id: int | None) -> DailyReportHistory:
    if report_id is not None:
        history = (await db.execute(
            select(DailyReportHistory).where(DailyReportHistory.id == report_id)
        )).scalar_one_or_none()
        if history is None:
            raise RuntimeError(f"Daily report {report_id} does not exist")
        if not _has_exact_snapshot(history):
            raise RuntimeError(
                f"Daily report {report_id} is a legacy record without an exact snapshot"
            )
        return history

    candidates = (await db.execute(
        select(DailyReportHistory)
        .order_by(DailyReportHistory.created_at.desc(), DailyReportHistory.id.desc())
        .limit(100)
    )).scalars().all()
    history = next((item for item in candidates if _has_exact_snapshot(item)), None)
    if history is None:
        raise RuntimeError(
            "No exact saved draft is available; generate a draft from the Daily Report page first"
        )
    return history


async def main() -> None:
    args = parse_args()
    try:
        async with SessionLocal() as db:
            history = await _load_history(db, args.report_id)
            service = DailyReportService(db)
            html, chart_images = service.build_draft_email(history, inline_images=True)
            snapshot = history.performance_summary["_report_snapshot"]

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(html, encoding="utf-8")
        ci = snapshot["yesterday"]["ci"]
        print(args.output.resolve())
        print(f"report_id={history.id} status={history.status} report_date={history.report_date}")
        print(
            f"nightly_total={ci['total_cases']} "
            f"nightly_passed={ci['passed_cases']} "
            f"nightly_failed={ci['failed_cases']} "
            f"nightly_pass_rate={ci['pass_rate']:.1f}"
        )
        print(f"charts={len(chart_images)} source=persisted_draft consistency=exact")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
