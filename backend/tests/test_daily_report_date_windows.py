from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.daily_report import DailyReportService


@pytest.mark.asyncio
async def test_report_date_is_used_for_every_yesterday_collector():
    service = DailyReportService(MagicMock())
    service._collect_ci_data = AsyncMock(return_value={})
    service._collect_model_data = AsyncMock(return_value={})
    service._collect_github_data = AsyncMock(return_value={})
    service._collect_perf_data = AsyncMock(return_value={})
    service._collect_resource_data = AsyncMock(return_value={})
    service._collect_test_data = AsyncMock(return_value={})
    service._collect_pr_pipeline_data = AsyncMock(return_value={})
    service._collect_diagnosis_stats = AsyncMock(return_value={})

    report = await service.generate_report(date(2026, 7, 17))

    expected_start = datetime(2026, 7, 16, 16, tzinfo=timezone.utc)
    expected_end = datetime(2026, 7, 17, 15, 59, 59, 999999, tzinfo=timezone.utc)
    service._collect_resource_data.assert_awaited_once_with(expected_start, expected_end)
    service._collect_test_data.assert_awaited_once_with(expected_start, expected_end)
    service._collect_pr_pipeline_data.assert_awaited_once_with(expected_start, expected_end)
    assert report["report_date"] == "2026-07-17"
    assert report["timezone"] == "Asia/Shanghai"
    assert report["report_window"] == {
        "start": "2026-07-17T00:00:00+08:00",
        "end": "2026-07-17T23:59:59.999999+08:00",
    }


@pytest.mark.asyncio
async def test_resource_query_uses_explicit_report_window(monkeypatch):
    query = AsyncMock(return_value={"clusters": []})

    class FakeResourceMetricsService:
        def __init__(self, db):
            pass

        query_npu_metrics = query

    monkeypatch.setattr(
        "app.services.resource_metrics.ResourceMetricsService",
        FakeResourceMetricsService,
    )
    service = DailyReportService(MagicMock())
    start = datetime(2026, 7, 16, 16, tzinfo=timezone.utc)
    end = datetime(2026, 7, 17, 15, 59, 59, 999999, tzinfo=timezone.utc)

    assert await service._collect_resource_data(start, end) == {"clusters": []}
    query.assert_awaited_once_with(time_range="24h", start_time=start, end_time=end)


@pytest.mark.asyncio
async def test_nightly_rate_counts_only_executed_a2_a3_test_cases():
    rows = [
        SimpleNamespace(workflow_name="Nightly A2", result="passed", duration_seconds=10),
        SimpleNamespace(workflow_name="schedule_nightly_test_a2", result="failed", duration_seconds=20),
        SimpleNamespace(workflow_name="Nightly-A3", result="success", duration_seconds=30),
        SimpleNamespace(workflow_name="Nightly A3", result="skipped", duration_seconds=None),
        SimpleNamespace(workflow_name="PR Check A2", result="failed", duration_seconds=40),
    ]
    scalar_result = MagicMock()
    scalar_result.scalars.return_value.all.return_value = rows
    db = MagicMock()
    db.execute = AsyncMock(return_value=scalar_result)
    service = DailyReportService(db)

    data = await service._collect_ci_data(
        datetime(2026, 7, 16, 16, tzinfo=timezone.utc),
        datetime(2026, 7, 17, 15, 59, 59, tzinfo=timezone.utc),
    )

    assert data["total_cases"] == 3
    assert data["passed_cases"] == 2
    assert data["failed_cases"] == 1
    assert data["pass_rate"] == pytest.approx(66.6667, rel=1e-4)
    assert data["by_hardware"] == [
        {"hardware": "A2", "total_cases": 2, "passed_cases": 1, "failed_cases": 1, "pass_rate": 50.0},
        {"hardware": "A3", "total_cases": 1, "passed_cases": 1, "failed_cases": 0, "pass_rate": 100.0},
    ]


def test_draft_uses_persisted_report_snapshot_without_requerying():
    snapshot = {
        "report_date": "2026-07-18",
        "timezone": "Asia/Shanghai",
        "yesterday": {"ci": {"total_cases": 34}},
    }
    history = SimpleNamespace(
        report_date="2026-07-18",
        ci_summary={"total_cases": 999},
        model_summary={},
        github_summary={},
        performance_summary={"avg_throughput": 1, "_report_snapshot": snapshot},
    )

    assert DailyReportService._get_draft_report_snapshot(history) is snapshot


def test_legacy_draft_snapshot_fallback_remains_sendable():
    history = SimpleNamespace(
        report_date="2026-07-18",
        ci_summary={"total_cases": 34},
        model_summary={"total_reports": 2},
        github_summary={"pr_count": 1},
        performance_summary={"avg_throughput": 10},
    )

    snapshot = DailyReportService._get_draft_report_snapshot(history)

    assert snapshot["yesterday"]["ci"] == {"total_cases": 34}
    assert snapshot["yesterday"]["performance"] == {"avg_throughput": 10}


def test_preview_and_delivery_share_the_same_email_renderer(monkeypatch):
    snapshot = {"report_date": "2026-07-18", "yesterday": {"ci": {}}}
    history = SimpleNamespace(
        report_date="2026-07-18",
        ai_report_content="# Daily report",
        performance_summary={"_report_snapshot": snapshot},
        ci_summary={}, model_summary={}, github_summary={},
    )
    monkeypatch.setattr(
        "app.services.chart_renderer.render_charts",
        lambda data: {"nightly": b"png-bytes"},
    )
    service = DailyReportService(MagicMock())

    delivery_html, delivery_images = service.build_draft_email(history)
    preview_html, preview_images = service.build_draft_email(history, inline_images=True)

    assert delivery_images == preview_images == {"nightly": b"png-bytes"}
    assert 'src="cid:nightly"' in delivery_html
    assert 'src="data:image/png;base64,cG5nLWJ5dGVz"' in preview_html
    assert delivery_html.replace('cid:nightly', 'data:image/png;base64,cG5nLWJ5dGVz') == preview_html
