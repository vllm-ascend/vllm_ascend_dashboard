from types import SimpleNamespace

from scripts.generate_real_daily_preview import _has_exact_snapshot


def test_exact_preview_requires_saved_ai_content_and_snapshot():
    exact = SimpleNamespace(
        ai_report_content="# report",
        performance_summary={"_report_snapshot": {"report_date": "2026-07-19"}},
    )
    assert _has_exact_snapshot(exact) is True


def test_legacy_or_incomplete_report_is_not_exact_previewable():
    legacy = SimpleNamespace(
        ai_report_content="# report",
        performance_summary={"avg_duration": 12},
    )
    missing_content = SimpleNamespace(
        ai_report_content=None,
        performance_summary={"_report_snapshot": {"report_date": "2026-07-19"}},
    )
    assert _has_exact_snapshot(legacy) is False
    assert _has_exact_snapshot(missing_content) is False
