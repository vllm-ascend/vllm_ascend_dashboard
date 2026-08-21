from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.routing import APIRoute

from api.v1.ci import batch_update_failure_status, router, update_failure_status
from contracts.schemas import DailyFailureBatchUpdateRequest, DailyFailureUpdateRequest


def _record(record_id: int, owner: str | None):
    return SimpleNamespace(
        id=record_id,
        job_id=record_id + 1000,
        run_id=record_id + 2000,
        workflow_name="Nightly-A3",
        job_name=f"job-{record_id}",
        conclusion="failure",
        started_at=None,
        completed_at=None,
        duration_seconds=None,
        hardware="A3",
        owner=owner,
        display_name=None,
        test_model=None,
        model_fo=None,
        deployment_type=None,
        processing_time=None,
        closure_time=None,
        processing_status="未处理",
        problem_category=None,
        related_pr=None,
        notes=None,
        updated_by=None,
        status_updated_at=None,
        github_job_url=None,
    )


@pytest.mark.parametrize(
    "path",
    ["/daily-failures/batch-status", "/daily-failures/batch-analyze"],
)
def test_batch_ids_are_declared_as_query_parameters(path: str):
    route = next(route for route in router.routes if isinstance(route, APIRoute) and route.path == path)

    query_names = {parameter.name for parameter in route.dependant.query_params}
    body_names = {parameter.name for parameter in route.dependant.body_params}
    assert "ids" in query_names
    assert "ids" not in body_names


@pytest.mark.asyncio
async def test_single_update_persists_normalized_owner():
    record = _record(1, None)
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: record)

    response = await update_failure_status(
        record_id=record.id,
        update=DailyFailureUpdateRequest(processing_status="处理中", owner="  alice  "),
        current_user=SimpleNamespace(username="admin", role="admin"),
        db=db,
    )

    assert record.owner == "alice"
    assert response.owner == "alice"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_batch_update_persists_owner_for_every_selected_record():
    records = [_record(1, None), _record(2, "old-owner")]
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: records),
    )

    response = await batch_update_failure_status(
        ids=[record.id for record in records],
        update=DailyFailureBatchUpdateRequest(owner="  bob  "),
        current_user=SimpleNamespace(username="admin", role="admin"),
        db=db,
    )

    assert [record.owner for record in records] == ["bob", "bob"]
    assert response["count"] == 2
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_batch_update_can_explicitly_clear_owner():
    record = _record(1, "alice")
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [record]),
    )

    await batch_update_failure_status(
        ids=[record.id],
        update=DailyFailureBatchUpdateRequest(owner=None),
        current_user=SimpleNamespace(username="admin", role="admin"),
        db=db,
    )

    assert record.owner is None
