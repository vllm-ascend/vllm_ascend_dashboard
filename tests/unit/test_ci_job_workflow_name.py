from types import SimpleNamespace

import pytest

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


@pytest.mark.asyncio
async def test_force_refresh_repairs_legacy_run_workflow_name():
    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    class Db:
        def __init__(self, values):
            self.values = iter(values)

        async def execute(self, _statement):
            return Result(next(self.values))

    legacy_result = SimpleNamespace(
        workflow_name="Nightly-A5 (scheduled)",
        status="completed",
        conclusion="failure",
        run_number=1,
        event="workflow_dispatch",
        branch="main",
        head_sha="a" * 40,
        completed_at=None,
        duration_seconds=None,
        hardware="A5",
        data="{}",
    )
    db = Db(["Nightly-A5", legacy_result])
    collector = CICollector(github_client=None, db_session=db)  # type: ignore[arg-type]

    updated = await collector._save_ci_result(
        {
            "id": 1,
            "status": "completed",
            "conclusion": "failure",
            "run_number": 1,
            "event": "workflow_dispatch",
            "head_branch": "main",
            "head_sha": "a" * 40,
            "updated_at": None,
        },
        "schedule_nightly_test_a5.yaml",
        "A5",
    )

    assert updated is True
    assert legacy_result.workflow_name == "Nightly-A5"
