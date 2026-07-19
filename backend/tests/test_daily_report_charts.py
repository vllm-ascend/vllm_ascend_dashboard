from app.services.chart_renderer import render_charts


def test_nightly_chart_uses_a2_a3_case_statistics():
    report = {
        "yesterday": {
            "ci": {
                "by_hardware": [
                    {"hardware": "A2", "passed_cases": 8, "failed_cases": 2, "pass_rate": 80.0},
                    {"hardware": "A3", "passed_cases": 9, "failed_cases": 0, "pass_rate": 100.0},
                ]
            }
        }
    }

    charts = render_charts(report)

    assert "nightly_case_pass_rate" in charts
    assert charts["nightly_case_pass_rate"].startswith(b"\x89PNG\r\n\x1a\n")


def test_nightly_chart_handles_hardware_with_no_executed_cases():
    report = {
        "yesterday": {
            "ci": {
                "by_hardware": [
                    {"hardware": "A2", "passed_cases": 0, "failed_cases": 0, "pass_rate": 0.0},
                    {"hardware": "A3", "passed_cases": 34, "failed_cases": 0, "pass_rate": 100.0},
                ]
            }
        }
    }

    chart = render_charts(report)["nightly_case_pass_rate"]

    assert chart.startswith(b"\x89PNG\r\n\x1a\n")
