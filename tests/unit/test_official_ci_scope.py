from types import SimpleNamespace

from sqlalchemy.dialects import mysql

from infrastructure.persistence.models import CIResult
from tooling.official_ci_scope import build_official_ci_filter


def test_official_scope_uses_enabled_workflow_identity_only():
    config = SimpleNamespace(
        workflow_name="Nightly-A3",
        event="workflow_dispatch",
        actor="ci-bot",
        stats_start_hour=20,
        stats_end_hour=8,
    )
    sql = str(
        build_official_ci_filter(CIResult, [config]).compile(
            dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "workflow_name" in sql
    assert "workflow_dispatch" not in sql
    assert "$.actor.login" not in sql
    assert "stats_start_hour" not in sql


def test_empty_official_scope_matches_nothing():
    sql = str(
        build_official_ci_filter(CIResult, []).compile(
            dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "= -1" in sql
