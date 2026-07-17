"""Self-tests for test board metadata feature (Issue: 用例元数据维护).

Covers:
- is_flaky_manual protection: auto detection must not overwrite a manual Flaky flag.
- Lifetime counters default to 0 for new cases.
- TestCaseUpdateRequest schema accepts partial updates.
- PATCH update logic: only provided fields are changed; is_flaky defaults to manual lock.
"""
from datetime import UTC, datetime, timedelta

import pytest

from app.schemas.test_board import TestCaseResponse, TestCaseUpdateRequest
from app.services.test_health_calculator import TestHealthCalculator
from tests.conftest import make_test_case, make_test_run


class TestFlakyManualProtection:
    """is_flaky_manual=True 时，自动检测不得覆盖 is_flaky。"""

    @pytest.mark.asyncio
    async def test_manual_flaky_not_overwritten_by_auto_detection(self, db_session):
        """人工锁定 Flaky=True 后，自动检测（应为 False）不能覆盖。"""
        now = datetime.now(UTC)
        case = make_test_case(test_name="test_manual_flaky", is_flaky=True)
        case.is_flaky_manual = True
        db_session.add(case)
        await db_session.flush()

        # 全部通过的稳定运行 —— 自动检测会判定 is_flaky=False
        for i in range(6):
            db_session.add(make_test_run(
                test_case_id=case.id,
                result="passed",
                duration_seconds=50.0,
                head_sha=f"sha{i}",
                started_at=now - timedelta(days=i),
            ))
        await db_session.commit()

        calc = TestHealthCalculator(db_session)
        await calc.calculate_all_health_scores()

        assert case.is_flaky_manual is True, "人工锁定标记应保持 True"
        assert case.is_flaky is True, "人工标记的 is_flaky=True 不应被自动检测覆盖为 False"

    @pytest.mark.asyncio
    async def test_auto_detection_works_when_not_manual(self, db_session):
        """未锁定时，自动检测正常设置 is_flaky。"""
        now = datetime.now(UTC)
        case = make_test_case(test_name="test_auto_flaky", is_flaky=False)
        case.is_flaky_manual = False
        db_session.add(case)
        await db_session.flush()

        results = ["passed", "failed", "passed", "failed", "passed", "failed"]
        for i, result in enumerate(results):
            db_session.add(make_test_run(
                test_case_id=case.id,
                result=result,
                duration_seconds=60.0,
                head_sha=f"sha{i // 2}",
                started_at=now - timedelta(days=i),
            ))
        await db_session.commit()

        calc = TestHealthCalculator(db_session)
        await calc.calculate_all_health_scores()

        assert case.is_flaky_manual is False
        # flaky_rate > 0 说明检测到翻转
        assert case.flaky_rate > 0


class TestLifetimeCountersDefault:
    """新用例的全生命周期计数默认为 0。"""

    @pytest.mark.asyncio
    async def test_new_case_has_zero_lifetime_counters(self, db_session):
        case = make_test_case(test_name="test_lifetime_default")
        db_session.add(case)
        await db_session.commit()

        assert case.lifetime_runs == 0
        assert case.lifetime_failures == 0
        assert case.issues_found == 0
        assert case.suspected_test_issue_count == 0
        assert case.is_flaky_manual is False

    @pytest.mark.asyncio
    async def test_response_schema_includes_new_fields(self, db_session):
        """TestCaseResponse 序列化包含所有新字段。"""
        case = make_test_case(test_name="test_schema_fields")
        case.lifetime_runs = 42
        case.lifetime_failures = 3
        db_session.add(case)
        await db_session.commit()

        resp = TestCaseResponse.model_validate(case)
        assert resp.lifetime_runs == 42
        assert resp.lifetime_failures == 3
        assert resp.issues_found == 0
        assert resp.suspected_test_issue_count == 0
        assert resp.is_flaky_manual is False
        assert resp.first_seen_at is not None
        assert resp.total_failed == 0


class TestUpdateRequestSchema:
    """TestCaseUpdateRequest 接受部分更新。"""

    def test_all_none_is_valid(self):
        req = TestCaseUpdateRequest()
        assert req.issues_found is None
        assert req.is_flaky is None
        assert req.owner is None

    def test_partial_update(self):
        req = TestCaseUpdateRequest(issues_found=5, is_flaky=True)
        assert req.issues_found == 5
        assert req.is_flaky is True
        assert req.owner is None  # 未提供

    def test_owner_clear_via_empty(self):
        req = TestCaseUpdateRequest(owner="")
        assert req.owner == ""


class TestPatchUpdateLogic:
    """模拟 PATCH 端点的更新逻辑（不经过 HTTP，直接验证字段赋值语义）。"""

    @pytest.mark.asyncio
    async def test_update_only_provided_fields(self, db_session):
        case = make_test_case(test_name="test_patch_partial", owner="alice")
        case.issues_found = 2
        db_session.add(case)
        await db_session.commit()

        original_owner = case.owner
        request = TestCaseUpdateRequest(issues_found=10)

        # 复制端点逻辑
        if request.issues_found is not None:
            case.issues_found = request.issues_found
        if request.owner is not None:
            case.owner = request.owner or None
        await db_session.commit()

        assert case.issues_found == 10, "已提供字段应更新"
        assert case.owner == original_owner, "未提供字段应保持不变"

    @pytest.mark.asyncio
    async def test_setting_is_flaky_locks_manual_by_default(self, db_session):
        """人工设置 is_flaky 时，若未显式指定 is_flaky_manual，默认锁定。"""
        case = make_test_case(test_name="test_patch_flaky", is_flaky=False)
        case.is_flaky_manual = False
        db_session.add(case)
        await db_session.commit()

        request = TestCaseUpdateRequest(is_flaky=True)
        if request.is_flaky_manual is not None:
            case.is_flaky_manual = request.is_flaky_manual
        if request.is_flaky is not None:
            case.is_flaky = request.is_flaky
            if request.is_flaky_manual is None:
                case.is_flaky_manual = True
        await db_session.commit()

        assert case.is_flaky is True
        assert case.is_flaky_manual is True, "设置 is_flaky 后应默认锁定为人工维护"

    @pytest.mark.asyncio
    async def test_unlock_manual_restores_auto(self, db_session):
        """显式 is_flaky_manual=False 可恢复自动检测。"""
        case = make_test_case(test_name="test_patch_unlock", is_flaky=True)
        case.is_flaky_manual = True
        db_session.add(case)
        await db_session.commit()

        request = TestCaseUpdateRequest(is_flaky_manual=False)
        if request.is_flaky_manual is not None:
            case.is_flaky_manual = request.is_flaky_manual
        await db_session.commit()

        assert case.is_flaky_manual is False

    @pytest.mark.asyncio
    async def test_clear_owner_with_empty_string(self, db_session):
        """空字符串应清空 owner。"""
        case = make_test_case(test_name="test_patch_clear_owner", owner="bob")
        db_session.add(case)
        await db_session.commit()

        request = TestCaseUpdateRequest(owner="")
        if request.owner is not None:
            case.owner = request.owner or None
        await db_session.commit()

        assert case.owner is None
