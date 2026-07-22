"""Tests for the bundled test case feature matrix snapshot and API."""

import os

os.environ["DEBUG"] = "false"
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("GITHUB_TOKEN", "ghp_test_token")
os.environ.setdefault("GITHUB_OWNER", "vllm-ascend")
os.environ.setdefault("GITHUB_REPO", "vllm-ascend")

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user
from app.api.v1.test_board import router as test_board_router
from app.models import User
from app.services.test_case_matrix_service import get_case_feature_matrix, resolve_case_matrix_path


def test_case_matrix_snapshot_is_bundled():
    path = resolve_case_matrix_path()

    assert path.is_file()
    assert path.name == "e2e_feature_matrix.csv"


def test_case_matrix_parser_returns_expected_statistics():
    data = get_case_feature_matrix()

    assert data["source_file"] == "e2e_feature_matrix.csv"
    assert data["statistics"]["total_cases"] == 289
    assert data["statistics"]["total_features"] == 57
    assert data["statistics"]["unmatched_cases"] == 2
    assert data["statistics"]["by_directory"] == {
        "pull_request": 84,
        "nightly": 121,
        "weekly": 84,
    }

    first_row = data["rows"][0]
    assert first_row["directory"] == "pull_request"
    assert first_row["case_name"].endswith("test_dense_model_310p.py")
    assert first_row["marked_feature_count"] == 3
    assert first_row["features"]["310p"] == "√"


@pytest_asyncio.fixture
async def matrix_client():
    app = FastAPI()
    app.include_router(test_board_router, prefix="/api/v1")

    user = User(
        id=1,
        username="matrix-user",
        password_hash="x",
        email="matrix@test.local",
        role="user",
        is_active=True,
    )

    async def override_current_user():
        return user

    app.dependency_overrides[get_current_user] = override_current_user
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


class TestCaseMatrixEndpoint:
    @pytest.mark.asyncio
    async def test_get_case_matrix_returns_snapshot(self, matrix_client):
        response = await matrix_client.get("/api/v1/test-board/case-matrix")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["source_file"] == "e2e_feature_matrix.csv"
        assert body["statistics"]["total_cases"] == 289
        assert body["statistics"]["by_directory"]["weekly"] == 84
        assert any(column["title"] == "310p" for column in body["feature_columns"])
        assert any(row["remark"] == "未直接命中特性池" for row in body["rows"])
