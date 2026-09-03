from failure_analysis.failure_analysis_pipeline import (
    normalize_ledger,
    programmatic_validate,
)


def test_direct_failure_can_complete_without_pr_regression_boundary():
    ledger = normalize_ledger(
        {
            "failure_facts": [
                "Job log reports no space left on device while preparing the runner."
            ],
            "stop_reason": "direct_failure_explained",
        }
    )

    validation = programmatic_validate(ledger)

    assert validation["verdict"] == "pass"
    assert validation["findings"] == []


def test_direct_failure_still_requires_primary_log_facts():
    ledger = normalize_ledger({"stop_reason": "direct_failure_explained"})

    validation = programmatic_validate(ledger)

    assert validation["verdict"] == "insufficient"
    assert validation["findings"][0]["code"] == "missing_failure_facts"
