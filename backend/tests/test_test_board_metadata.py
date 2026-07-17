"""Self-tests for test board metadata feature (Issue: 用例元数据维护).

Covers:
- is_flaky_manual protection: auto detection must not overwrite a manual Flaky flag.
- Lifetime counters default to 0 for new cases.
- TestCaseUpdateRequest schema accepts partial updates + input validation.
- PATCH update logic: only provided fields are changed; is_flaky=True locks manual.
- Real PATCH endpoint via httpx ASGITransport (检视意见 #4).
- _parse_job_results lifetime counter atomic increment (检视意见 #4).
- Backfill SQL correctness (检视意见 #4).
"""
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

# 确保设置校验在任何 app 导入前通过
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("GITHUB_TOKEN", "ghp_test_token")
os.environ.setdefault("GITHUB_OWNER", "vllm-ascend")
os.environ.setdefault("GITHUB_REPO", "vllm-ascend")

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models.test_board import TestCase as _TC
from app.schemas.test_board import TestCaseResponse, TestCaseUpdateRequest
from app.services.test_health_calculator import TestHealthCalculator
from tests.conftest import make_test_case, make_test_run


class TestFlakyManualProtection:
    """is_flaky_manual=True 时，自动检测不得覆盖 is_flaky。"""

    @pytest.mark.asyncio
    async def test_manual_flaky_not_overwritten_by_auto_detection(self, rich_db):
        """人工锁定 Flaky=True 后，自动检测（应为 False）不能覆盖。"""
        now = datetime.now(UTC)
        case = make_test_case(test_name="test_manual_flaky", is_flaky=True)
        case.is_flaky_manual = True
        rich_db.add(case)
        await rich_db.flush()

        # 全部通过的稳定运行 —— 自动检测会判定 is_flaky=False
        for i in range(6):
            rich_db.add(make_test_run(
                test_case_id=case.id,
                result="passed",
                duration_seconds=50.0,
                head_sha=f"sha{i}",
                started_at=now - timedelta(days=i),
            ))
        await rich_db.commit()

        calc = TestHealthCalculator(rich_db)
        await calc.calculate_all_health_scores()

        assert case.is_flaky_manual is True, "人工锁定标记应保持 True"
        assert case.is_flaky is True, "人工标记的 is_flaky=True 不应被自动检测覆盖为 False"

    @pytest.mark.asyncio
    async def test_auto_detection_works_when_not_manual(self, rich_db):
        """未锁定时，自动检测正常设置 is_flaky。"""
        now = datetime.now(UTC)
        case = make_test_case(test_name="test_auto_flaky", is_flaky=False)
        case.is_flaky_manual = False
        rich_db.add(case)
        await rich_db.flush()

        results = ["passed", "failed", "passed", "failed", "passed", "failed"]
        for i, result in enumerate(results):
            rich_db.add(make_test_run(
                test_case_id=case.id,
                result=result,
                duration_seconds=60.0,
                head_sha=f"sha{i // 2}",
                started_at=now - timedelta(days=i),
            ))
        await rich_db.commit()

        calc = TestHealthCalculator(rich_db)
        await calc.calculate_all_health_scores()

        assert case.is_flaky_manual is False
        # flaky_rate > 0 说明检测到翻转
        assert case.flaky_rate > 0


class TestLifetimeCountersDefault:
    """新用例的全生命周期计数默认为 0。"""

    @pytest.mark.asyncio
    async def test_new_case_has_zero_lifetime_counters(self, rich_db):
        case = make_test_case(test_name="test_lifetime_default")
        rich_db.add(case)
        await rich_db.commit()

        assert case.lifetime_runs == 0
        assert case.lifetime_failures == 0
        assert case.issues_found == 0
        assert case.suspected_test_issue_count == 0
        assert case.is_flaky_manual is False

    @pytest.mark.asyncio
    async def test_response_schema_includes_new_fields(self, rich_db):
        """TestCaseResponse 序列化包含所有新字段。"""
        case = make_test_case(test_name="test_schema_fields")
        case.lifetime_runs = 42
        case.lifetime_failures = 3
        rich_db.add(case)
        await rich_db.commit()

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

    def test_rejects_negative_issues_found(self):
        """检视意见 #1.1：负数应被拒绝。"""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            TestCaseUpdateRequest(issues_found=-1)

    def test_rejects_negative_suspected_count(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            TestCaseUpdateRequest(suspected_test_issue_count=-3)

    def test_rejects_invalid_email(self):
        """检视意见 #1.2：邮箱格式校验。"""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            TestCaseUpdateRequest(owner_email="not-an-email")

    def test_accepts_valid_email(self):
        req = TestCaseUpdateRequest(owner_email="dev@example.com")
        assert req.owner_email == "dev@example.com"


class TestPatchUpdateLogic:
    """模拟 PATCH 端点的更新逻辑（不经过 HTTP，直接验证字段赋值语义）。"""

    @pytest.mark.asyncio
    async def test_update_only_provided_fields(self, rich_db):
        case = make_test_case(test_name="test_patch_partial", owner="alice")
        case.issues_found = 2
        rich_db.add(case)
        await rich_db.commit()

        original_owner = case.owner
        request = TestCaseUpdateRequest(issues_found=10)

        # 复制端点逻辑
        if request.issues_found is not None:
            case.issues_found = request.issues_found
        if request.owner is not None:
            case.owner = request.owner or None
        await rich_db.commit()

        assert case.issues_found == 10, "已提供字段应更新"
        assert case.owner == original_owner, "未提供字段应保持不变"

    @pytest.mark.asyncio
    async def test_setting_is_flaky_true_locks_manual_by_default(self, rich_db):
        """人工设置 is_flaky=True 时，若未显式指定 is_flaky_manual，默认锁定。"""
        case = make_test_case(test_name="test_patch_flaky", is_flaky=False)
        case.is_flaky_manual = False
        rich_db.add(case)
        await rich_db.commit()

        request = TestCaseUpdateRequest(is_flaky=True)
        if request.is_flaky_manual is not None:
            case.is_flaky_manual = request.is_flaky_manual
        if request.is_flaky is not None:
            case.is_flaky = request.is_flaky
            # 仅 is_flaky=True 时自动锁定（修复检视意见 #5：False 不应锁定）
            if request.is_flaky_manual is None and request.is_flaky is True:
                case.is_flaky_manual = True
        await rich_db.commit()

        assert case.is_flaky is True
        assert case.is_flaky_manual is True, "设置 is_flaky=True 后应默认锁定为人工维护"

    @pytest.mark.asyncio
    async def test_setting_is_flaky_false_does_not_lock(self, rich_db):
        """标记为稳定（is_flaky=False）不应自动锁定人工模式，保留自动检测。"""
        case = make_test_case(test_name="test_patch_stable", is_flaky=True)
        case.is_flaky_manual = False
        rich_db.add(case)
        await rich_db.commit()

        request = TestCaseUpdateRequest(is_flaky=False)
        if request.is_flaky_manual is not None:
            case.is_flaky_manual = request.is_flaky_manual
        if request.is_flaky is not None:
            case.is_flaky = request.is_flaky
            if request.is_flaky_manual is None and request.is_flaky is True:
                case.is_flaky_manual = True
        await rich_db.commit()

        assert case.is_flaky is False
        assert case.is_flaky_manual is False, "标记为稳定不应锁定人工模式"

    @pytest.mark.asyncio
    async def test_unlock_manual_restores_auto(self, rich_db):
        """显式 is_flaky_manual=False 可恢复自动检测。"""
        case = make_test_case(test_name="test_patch_unlock", is_flaky=True)
        case.is_flaky_manual = True
        rich_db.add(case)
        await rich_db.commit()

        request = TestCaseUpdateRequest(is_flaky_manual=False)
        if request.is_flaky_manual is not None:
            case.is_flaky_manual = request.is_flaky_manual
        await rich_db.commit()

        assert case.is_flaky_manual is False

    @pytest.mark.asyncio
    async def test_clear_owner_with_empty_string(self, rich_db):
        """空字符串应清空 owner。"""
        case = make_test_case(test_name="test_patch_clear_owner", owner="bob")
        rich_db.add(case)
        await rich_db.commit()

        request = TestCaseUpdateRequest(owner="")
        if request.owner is not None:
            case.owner = request.owner or None
        await rich_db.commit()

        assert case.owner is None


# ============================================================================
# 检视意见 #4：真实端点级测试（httpx ASGITransport + 依赖覆盖）
# ============================================================================


@pytest.fixture
async def app_client(rich_db):
    """构造一个覆盖了 get_db / get_current_user 的真实 ASGI 测试客户端。

    使用自带的 rich_db（内存 SQLite），不依赖 conftest 的 MySQL fixture，
    便于本地与 CI 一致运行。采用最小 FastAPI app（仅挂载 test_board 路由），
    避免 app.main 的中间件触发 MySQL 连接。
    """
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api.deps import get_current_user, get_db
    from app.api.v1.test_board import router as test_board_router
    from app.models import User

    app = FastAPI()
    app.include_router(test_board_router, prefix="/api/v1")

    super_admin = User(
        id=1, username="superadmin", password_hash="x",
        email="admin@test.local", role="super_admin", is_active=True,
    )

    async def override_get_db():
        yield rich_db

    async def override_current_user():
        return super_admin

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current_user
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, rich_db
    finally:
        app.dependency_overrides.clear()


class TestPatchEndpoint:
    """真实 PATCH /test-board/cases/{id} 端点测试。"""

    @pytest.mark.asyncio
    async def test_update_issues_found_returns_200(self, app_client):
        client, db = app_client
        case = make_test_case(test_name="ep_update")
        case.issues_found = 0
        db.add(case)
        await db.commit()

        resp = await client.patch(f"/api/v1/test-board/cases/{case.id}", json={"issues_found": 7})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["issues_found"] == 7

        # 验证 DB 真实更新
        refreshed = (await db.execute(select(_TC).where(_TC.id == case.id))).scalar_one()
        assert refreshed.issues_found == 7

    @pytest.mark.asyncio
    async def test_is_flaky_false_does_not_lock(self, app_client):
        """检视意见 #5：标记稳定不应锁定人工模式。"""
        client, db = app_client
        case = make_test_case(test_name="ep_stable", is_flaky=True)
        case.is_flaky_manual = False
        db.add(case)
        await db.commit()

        resp = await client.patch(f"/api/v1/test-board/cases/{case.id}", json={"is_flaky": False})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["is_flaky"] is False
        assert body["is_flaky_manual"] is False, "标记为稳定不应自动锁定人工模式"

    @pytest.mark.asyncio
    async def test_is_flaky_true_auto_locks(self, app_client):
        client, db = app_client
        case = make_test_case(test_name="ep_flaky_lock", is_flaky=False)
        case.is_flaky_manual = False
        db.add(case)
        await db.commit()

        resp = await client.patch(f"/api/v1/test-board/cases/{case.id}", json={"is_flaky": True})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["is_flaky"] is True
        assert body["is_flaky_manual"] is True, "标记为 Flaky 应自动锁定"

    @pytest.mark.asyncio
    async def test_rejects_negative_issues_found(self, app_client):
        """检视意见 #1.1：负数应返回 422。"""
        client, db = app_client
        case = make_test_case(test_name="ep_neg")
        db.add(case)
        await db.commit()

        resp = await client.patch(f"/api/v1/test-board/cases/{case.id}", json={"issues_found": -1})
        assert resp.status_code == 422, resp.text

    @pytest.mark.asyncio
    async def test_rejects_invalid_email(self, app_client):
        """检视意见 #1.2：邮箱格式校验应返回 422。"""
        client, db = app_client
        case = make_test_case(test_name="ep_email")
        db.add(case)
        await db.commit()

        resp = await client.patch(f"/api/v1/test-board/cases/{case.id}", json={"owner_email": "not-an-email"})
        assert resp.status_code == 422, resp.text

    @pytest.mark.asyncio
    async def test_404_unknown_case(self, app_client):
        client, _ = app_client
        resp = await client.patch("/api/v1/test-board/cases/999999", json={"issues_found": 1})
        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_clear_owner_with_empty_string(self, app_client):
        client, db = app_client
        case = make_test_case(test_name="ep_clear_owner", owner="bob")
        db.add(case)
        await db.commit()

        resp = await client.patch(f"/api/v1/test-board/cases/{case.id}", json={"owner": ""})
        assert resp.status_code == 200, resp.text
        assert resp.json()["owner"] is None

    @pytest.mark.asyncio
    async def test_partial_update_preserves_other_fields(self, app_client):
        client, db = app_client
        case = make_test_case(test_name="ep_partial", owner="alice")
        case.issues_found = 2
        db.add(case)
        await db.commit()

        resp = await client.patch(f"/api/v1/test-board/cases/{case.id}", json={"suspected_test_issue_count": 5})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["suspected_test_issue_count"] == 5
        assert body["owner"] == "alice", "未提供字段应保持不变"
        assert body["issues_found"] == 2


# ============================================================================
# 检视意见 #4：_parse_job_results 生命周期计数原子递增测试
# ============================================================================


@pytest.fixture
async def rich_db():
    """自带内存 SQLite 库，包含 test_board 相关全部表，供本模块所有 DB 测试使用。

    不依赖 conftest 的 MySQL db_session，本地与 CI 一致运行。
    """
    from app.models import Base, CIResult, JobOwner
    from app.models.test_board import TestCase, TestRun, TestSuiteSnapshot

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=[
                    CIResult.__table__, JobOwner.__table__,
                    TestCase.__table__, TestRun.__table__, TestSuiteSnapshot.__table__,
                ]
            )
        )
    sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sf() as session:
        yield session
    await engine.dispose()


class TestParseJobResultsIncrement:
    """_parse_job_results 应原子递增 lifetime_runs / lifetime_failures。"""

    @pytest.mark.asyncio
    async def test_failed_run_increments_both_counters(self, rich_db):
        from app.models import CIJob, CIResult
        from app.services.test_board_service import TestBoardService

        now = datetime.now(UTC)
        rich_db.add(CIResult(
            workflow_name="Nightly-A2", run_id=100, run_number=1, status="completed",
            conclusion="failure", event="schedule", branch="main", head_sha="abc",
            started_at=now, completed_at=now, duration_seconds=60, hardware="A2",
        ))
        await rich_db.commit()

        ci_job = CIJob(
            job_id=200, run_id=100, workflow_name="Nightly-A2",
            job_name="single-node (main, Qwen3-8B)", status="completed",
            conclusion="failure", started_at=now, completed_at=now,
            duration_seconds=60, hardware="A2",
        )

        mock_gh = MagicMock()
        mock_gh.list_artifacts = AsyncMock(return_value=[])
        mock_gh.download_artifact = AsyncMock(return_value=b"")
        classifier = MagicMock()
        classifier.classify = AsyncMock(return_value=("product_bug", 0.7))

        svc = TestBoardService(rich_db, mock_gh)
        count = await svc._parse_job_results(ci_job, classifier)
        await rich_db.commit()

        assert count == 1, "应解析出 1 个用例级结果"
        from app.models.test_board import TestCase as TC
        case = (await rich_db.execute(select(TC).where(TC.test_name == "single-node (main, Qwen3-8B)"))).scalar_one()
        assert case.lifetime_runs == 1, "lifetime_runs 应递增到 1"
        assert case.lifetime_failures == 1, "失败结果应同时递增 lifetime_failures"

    @pytest.mark.asyncio
    async def test_passed_run_increments_only_runs(self, rich_db):
        from app.models import CIJob, CIResult
        from app.services.test_board_service import TestBoardService

        now = datetime.now(UTC)
        rich_db.add(CIResult(
            workflow_name="Nightly-A2", run_id=101, run_number=1, status="completed",
            conclusion="success", event="schedule", branch="main", head_sha="def",
            started_at=now, completed_at=now, duration_seconds=60, hardware="A2",
        ))
        await rich_db.commit()

        ci_job = CIJob(
            job_id=201, run_id=101, workflow_name="Nightly-A2",
            job_name="single-node (main, Qwen3-8B)", status="completed",
            conclusion="success", started_at=now, completed_at=now,
            duration_seconds=60, hardware="A2",
        )

        mock_gh = MagicMock()
        mock_gh.list_artifacts = AsyncMock(return_value=[])
        classifier = MagicMock()
        classifier.classify = AsyncMock(return_value=("unknown", 0.0))

        svc = TestBoardService(rich_db, mock_gh)
        await svc._parse_job_results(ci_job, classifier)
        await rich_db.commit()

        from app.models.test_board import TestCase as TC
        case = (await rich_db.execute(select(TC).where(TC.test_name == "single-node (main, Qwen3-8B)"))).scalar_one()
        assert case.lifetime_runs == 1
        assert case.lifetime_failures == 0, "通过结果不应递增 lifetime_failures"


# ============================================================================
# 检视意见 #4：回填 SQL 正确性测试
# ============================================================================


class TestBackfillLogic:
    """验证回填 SQL 从 test_runs 正确统计生命周期计数。"""

    @pytest.mark.asyncio
    async def test_backfill_counts_runs_and_failures(self, rich_db):
        from app.models.test_board import TestCase as TC

        case = make_test_case(test_name="bf_case", test_suite="Nightly-A2")
        case.lifetime_runs = 0
        case.lifetime_failures = 0
        rich_db.add(case)
        await rich_db.flush()

        now = datetime.now(UTC)
        # 3 次运行，其中 1 次失败
        for i, result in enumerate(["passed", "failed", "passed"]):
            rich_db.add(make_test_run(
                test_case_id=case.id, result=result,
                started_at=now - timedelta(days=i),
            ))
        await rich_db.commit()

        # 执行与迁移相同的回填 SQL
        await rich_db.execute(text(
            "UPDATE test_cases SET lifetime_runs = ("
            "  SELECT COUNT(*) FROM test_runs WHERE test_runs.test_case_id = test_cases.id"
            ") WHERE id = :cid"
        ), {"cid": case.id})
        await rich_db.execute(text(
            "UPDATE test_cases SET lifetime_failures = ("
            "  SELECT COUNT(*) FROM test_runs WHERE test_runs.test_case_id = test_cases.id"
            "    AND test_runs.result = 'failed'"
            ") WHERE id = :cid"
        ), {"cid": case.id})
        await rich_db.commit()

        # 用原生 SQL 校验，避免 ORM 身份映射缓存导致读到旧值
        row = (await rich_db.execute(
            text("SELECT lifetime_runs, lifetime_failures FROM test_cases WHERE id = :cid"),
            {"cid": case.id},
        )).one()
        assert row[0] == 3, "应回填为 3 次运行"
        assert row[1] == 1, "应回填为 1 次失败"
