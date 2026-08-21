from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from contracts.schemas import DailyFailureBatchUpdateRequest
from failure_analysis.failure_analysis import FailureAnalysisService


def _result(records):
    return SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: records),
    )


@pytest.mark.asyncio
async def test_sync_problem_category_prefers_job_id_match():
    record = SimpleNamespace(problem_category=None)
    db = AsyncMock()
    db.execute.return_value = _result([record])

    changed = await FailureAnalysisService._sync_problem_category_to_daily_failure(
        db,
        job_id=123,
        run_id=456,
        workflow_name="Nightly-A3",
        job_name="test-job",
        problem_category="开发代码",
    )

    assert changed == 1
    assert record.problem_category == "开发代码"
    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_sync_problem_category_falls_back_for_legacy_daily_record():
    record = SimpleNamespace(problem_category="其他")
    db = AsyncMock()
    db.execute.side_effect = [_result([]), _result([record])]

    changed = await FailureAnalysisService._sync_problem_category_to_daily_failure(
        db,
        job_id=123,
        run_id=456,
        workflow_name="Nightly-A3",
        job_name="test-job",
        problem_category="基础设施",
    )

    assert changed == 1
    assert record.problem_category == "基础设施"
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_sync_problem_category_ignores_empty_category():
    db = AsyncMock()

    changed = await FailureAnalysisService._sync_problem_category_to_daily_failure(
        db,
        job_id=123,
        run_id=456,
        workflow_name="Nightly-A3",
        job_name="test-job",
        problem_category=None,
    )

    assert changed == 0
    db.execute.assert_not_awaited()


def test_daily_failure_batch_update_preserves_unset_fields():
    update = DailyFailureBatchUpdateRequest(processing_status="处理中")

    assert update.model_fields_set == {"processing_status"}
    assert update.model_dump(exclude_unset=True) == {"processing_status": "处理中"}


def test_daily_failure_batch_update_tracks_owner_assignment():
    update = DailyFailureBatchUpdateRequest(owner="admin")

    assert update.model_fields_set == {"owner"}
    assert update.model_dump(exclude_unset=True) == {"owner": "admin"}


def test_daily_failure_batch_update_tracks_owner_clear():
    update = DailyFailureBatchUpdateRequest(owner=None)

    assert update.model_fields_set == {"owner"}
    assert update.model_dump(exclude_unset=True) == {"owner": None}
