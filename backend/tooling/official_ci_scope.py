"""Shared selection rules for dashboard-managed (official) CI runs."""
from collections.abc import Iterable
from typing import Any

from sqlalchemy import or_


def build_official_ci_filter(result_model: Any, configs: Iterable[Any]):
    """Return the enabled Workflow identity filter used by overview/history.

    ``stats_start_hour`` and ``stats_end_hour`` deliberately do not participate:
    they describe report windows, not the identity of an official run.
    Event and actor also do not participate: the homepage defines the covered
    Workflow set, while history must retain that Workflow's runs on every day.
    """
    clauses = []
    for config in configs:
        clauses.append(result_model.workflow_name == config.workflow_name)
    return or_(*clauses) if clauses else result_model.id == -1
