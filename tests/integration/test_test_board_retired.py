"""Self-tests for retired test case feature (已退出用例自动治理).

Covers:
- is_retired model_validator: computes correctly from last_run_at / first_seen_at
- is_retired with naive datetime (timezone compatibility)
- _active_case_filter: filters retired cases from queries
- cleanup_stale_cases: physically deletes old cases + their runs
- cleanup_stale_cases: handles never-run cases (last_run_at IS NULL)
- get_cases include_stale parameter behavior
"""
import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("GITHUB_TOKEN", "ghp_test_token")
os.environ.setdefault("GITHUB_OWNER", "vllm-ascend")
os.environ.setdefault("GITHUB_REPO", "vllm-ascend")

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.conftest import make_test_case, make_test_run
from tests.mysql_test_db import create_test_engine, reset_tables

from contracts.schemas.test_board import TestCaseResponse
from infrastructure.persistence.models.test_board import TestCase, TestRun
from test_board.test_board_service import TestBoardService
from tooling.analytics.test_health_calculator import TestHealthCalculator


@pytest.fixture
async def rich_db():
    from infrastructure.persistence.models import CIResult, JobOwner
    from infrastructure.persistence.models.test_board import TestSuiteSnapshot

    engine = create_test_engine()
    await reset_tables(engine, [
        CIResult.__table__, JobOwner.__table__, TestCase.__table__,
        TestRun.__table__, TestSuiteSnapshot.__table__,
    ])
    sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sf() as session:
        yield session
    await engine.dispose()


class TestIsRetiredValidator:
    """is_retired model_validator 从 last_run_at / first_seen_at 动态计算。"""

    @pytest.mark.asyncio
    async def test_recent_run_not_retired(self, rich_db):
        case = make_test_case(test_name="active_case")
        case.last_run_at = datetime.now(UTC) - timedelta(days=1)
        rich_db.add(case)
        await rich_db.flush()
        resp = TestCaseResponse.model_validate(case)
        assert resp.is_retired is False

    @pytest.mark.asyncio
    async def test_old_run_is_retired(self, rich_db):
        case = make_test_case(test_name="old_case")
        case.last_run_at = datetime.now(UTC) - timedelta(days=30)
        rich_db.add(case)
        await rich_db.flush()
        resp = TestCaseResponse.model_validate(case)
        assert resp.is_retired is True

    @pytest.mark.asyncio
    async def test_never_run_recent_create_not_retired(self, rich_db):
        case = make_test_case(test_name="new_no_run")
        case.last_run_at = None
        case.first_seen_at = datetime.now(UTC) - timedelta(days=1)
        rich_db.add(case)
        await rich_db.flush()
        resp = TestCaseResponse.model_validate(case)
        assert resp.is_retired is False

    @pytest.mark.asyncio
    async def test_never_run_old_create_is_retired(self, rich_db):
        case = make_test_case(test_name="old_no_run")
        case.last_run_at = None
        case.first_seen_at = datetime.now(UTC) - timedelta(days=30)
        rich_db.add(case)
        await rich_db.flush()
        resp = TestCaseResponse.model_validate(case)
        assert resp.is_retired is True

    @pytest.mark.asyncio
    async def test_naive_datetime_compatibility(self, rich_db):
        """naive datetime (无时区) 也能正确比较，不抛 TypeError。"""
        case = make_test_case(test_name="naive_case")
        case.last_run_at = datetime.now() - timedelta(days=30)  # naive
        rich_db.add(case)
        await rich_db.flush()
        resp = TestCaseResponse.model_validate(case)
        assert resp.is_retired is True


class TestActiveCaseFilter:
    """_active_case_filter 在查询中排除已退出用例。"""

    @pytest.mark.asyncio
    async def test_get_cases_excludes_retired_by_default(self, rich_db):
        active = make_test_case(test_name="active_test")
        active.last_run_at = datetime.now(UTC) - timedelta(days=1)
        active.last_seen_at = active.last_run_at

        retired = make_test_case(test_name="retired_test")
        retired.last_run_at = datetime.now(UTC) - timedelta(days=30)
        retired.last_seen_at = retired.last_run_at

        rich_db.add_all([active, retired])
        await rich_db.commit()

        svc = TestBoardService(rich_db)
        data = await svc.get_cases(include_stale=False)
        names = [c.test_name for c in data["items"]]
        assert "active_test" in names
        assert "retired_test" not in names
        assert data["total"] == 1

    @pytest.mark.asyncio
    async def test_get_cases_includes_retired_when_flag_set(self, rich_db):
        active = make_test_case(test_name="active_test")
        active.last_run_at = datetime.now(UTC) - timedelta(days=1)

        retired = make_test_case(test_name="retired_test")
        retired.last_run_at = datetime.now(UTC) - timedelta(days=30)

        rich_db.add_all([active, retired])
        await rich_db.commit()

        svc = TestBoardService(rich_db)
        data = await svc.get_cases(include_stale=True)
        names = [c.test_name for c in data["items"]]
        assert "active_test" in names
        assert "retired_test" in names
        assert data["total"] == 2

    @pytest.mark.asyncio
    async def test_overview_excludes_retired_from_stats(self, rich_db):
        active = make_test_case(test_name="active_pass", last_result="passed")
        active.last_run_at = datetime.now(UTC) - timedelta(days=1)
        active.pass_rate_7d = 1.0

        retired_fail = make_test_case(test_name="retired_fail", last_result="failed")
        retired_fail.last_run_at = datetime.now(UTC) - timedelta(days=30)
        retired_fail.pass_rate_7d = 0.0

        rich_db.add_all([active, retired_fail])
        await rich_db.commit()

        svc = TestBoardService(rich_db)
        overview = await svc.get_overview(include_stale=False)
        assert overview["total_cases"] == 1
        assert overview["attention_case_count"] == 0  # retired_fail excluded
        assert overview["stale_case_count"] == 1

    @pytest.mark.asyncio
    async def test_overview_includes_retired_when_flag_set(self, rich_db):
        active = make_test_case(test_name="active_pass", last_result="passed")
        active.last_run_at = datetime.now(UTC) - timedelta(days=1)

        retired_fail = make_test_case(test_name="retired_fail", last_result="failed")
        retired_fail.last_run_at = datetime.now(UTC) - timedelta(days=30)

        rich_db.add_all([active, retired_fail])
        await rich_db.commit()

        svc = TestBoardService(rich_db)
        overview = await svc.get_overview(include_stale=True)
        assert overview["total_cases"] == 2
        assert overview["attention_case_count"] == 1  # retired_fail included


class TestCleanupStaleCases:
    """cleanup_stale_cases 物理删除长期未运行的用例及其运行记录。"""

    @pytest.mark.asyncio
    async def test_deletes_old_case_with_runs(self, rich_db):
        old_case = make_test_case(test_name="very_old")
        old_case.last_run_at = datetime.now(UTC) - timedelta(days=120)
        rich_db.add(old_case)
        await rich_db.flush()

        rich_db.add(make_test_run(test_case_id=old_case.id, result="failed"))
        await rich_db.commit()

        calc = TestHealthCalculator(rich_db)
        deleted = await calc.cleanup_stale_cases()
        assert deleted == 1

        remaining = (await rich_db.execute(select(func.count(TestCase.id)))).scalar()
        assert remaining == 0
        runs = (await rich_db.execute(select(func.count(TestRun.id)))).scalar()
        assert runs == 0

    @pytest.mark.asyncio
    async def test_keeps_recent_case(self, rich_db):
        recent = make_test_case(test_name="recent")
        recent.last_run_at = datetime.now(UTC) - timedelta(days=3)
        rich_db.add(recent)
        await rich_db.commit()

        calc = TestHealthCalculator(rich_db)
        deleted = await calc.cleanup_stale_cases()
        assert deleted == 0

        remaining = (await rich_db.execute(select(func.count(TestCase.id)))).scalar()
        assert remaining == 1

    @pytest.mark.asyncio
    async def test_deletes_never_run_old_case(self, rich_db):
        """从未运行且创建超过阈值的用例也应当被删除 (I4 fix)。"""
        old_no_run = make_test_case(test_name="never_run_old")
        old_no_run.last_run_at = None
        old_no_run.first_seen_at = datetime.now(UTC) - timedelta(days=120)
        rich_db.add(old_no_run)
        await rich_db.commit()

        calc = TestHealthCalculator(rich_db)
        deleted = await calc.cleanup_stale_cases()
        assert deleted == 1

    @pytest.mark.asyncio
    async def test_keeps_never_run_recent_case(self, rich_db):
        """从未运行但近期创建的用例不应被删除。"""
        new_no_run = make_test_case(test_name="never_run_new")
        new_no_run.last_run_at = None
        new_no_run.first_seen_at = datetime.now(UTC) - timedelta(days=2)
        rich_db.add(new_no_run)
        await rich_db.commit()

        calc = TestHealthCalculator(rich_db)
        deleted = await calc.cleanup_stale_cases()
        assert deleted == 0


class TestFailureBreakdownExcludesRetired:
    """get_failure_breakdown 不对外暴露已退出用例的失败记录 (B3 fix)。"""

    @pytest.mark.asyncio
    async def test_failure_breakdown_excludes_retired_case_failures(self, rich_db):
        active = make_test_case(test_name="active_fail", last_result="failed")
        active.last_run_at = datetime.now(UTC) - timedelta(days=1)
        rich_db.add(active)
        await rich_db.flush()
        rich_db.add(make_test_run(
            test_case_id=active.id, result="failed",
            failure_category="product_bug",
            started_at=datetime.now(UTC) - timedelta(days=1),
        ))

        retired = make_test_case(test_name="retired_fail", last_result="failed")
        retired.last_run_at = datetime.now(UTC) - timedelta(days=30)
        rich_db.add(retired)
        await rich_db.flush()
        rich_db.add(make_test_run(
            test_case_id=retired.id, result="failed",
            failure_category="product_bug",
            started_at=datetime.now(UTC) - timedelta(days=30),
        ))
        await rich_db.commit()

        svc = TestBoardService(rich_db)
        breakdown = await svc.get_failure_breakdown(days=60)
        assert breakdown["total"] == 1  # only active case's failure
        assert breakdown["product_bug"] == 1
