from collector.ci import CICollector


def test_github_decorated_workflow_name_uses_configured_identity():
    assert (
        CICollector._match_configured_workflow_name(
            "Nightly-A5 (PR) 14544", "Nightly-A5"
        )
        == "Nightly-A5"
    )
    assert (
        CICollector._match_configured_workflow_name(
            "Nightly-A5 (scheduled)", "Nightly-A5"
        )
        == "Nightly-A5"
    )


def test_github_exact_workflow_name_uses_configured_identity():
    assert (
        CICollector._match_configured_workflow_name("Nightly-A3", "Nightly-A3")
        == "Nightly-A3"
    )
