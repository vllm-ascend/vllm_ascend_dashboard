"""代码度量下钻明细 API 集成测试。

使用 SQLite 内存数据库验证 /code-metrics/files, /functions, /drilldown 端点。
"""
import sys
from datetime import date
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

backend_dir = str(Path(__file__).resolve().parent.parent)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.api.deps import get_db  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, CodeComplexityDetail, CodeMetricsSnapshot, User  # noqa: E402


@pytest_asyncio.fixture
async def test_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def test_db(test_engine):
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_factory() as session:
        # 插入一条快照 + 若干复杂度明细
        snap = CodeMetricsSnapshot(
            repo="vllm-ascend",
            branch="main",
            snapshot_date=date(2026, 7, 20),
            total_loc=10000,
            total_functions=100,
            total_files=20,
            language_loc={"Python": 8000, "C++": 2000},
            module_loc={"vllm_ascend": 7000, "csrc": 2000, "tests": 1000},
        )
        session.add(snap)
        await session.flush()

        details = [
            CodeComplexityDetail(
                snapshot_id=snap.id,
                file_path="vllm_ascend/core/__init__.py",
                function_name="func_a",
                language="Python",
                cyclomatic_complexity=25,
                max_nesting_depth=6,
                function_lines=120,
                start_line=10,
            ),
            CodeComplexityDetail(
                snapshot_id=snap.id,
                file_path="vllm_ascend/core/__init__.py",
                function_name="func_b",
                language="Python",
                cyclomatic_complexity=5,
                max_nesting_depth=2,
                function_lines=30,
                start_line=150,
            ),
            CodeComplexityDetail(
                snapshot_id=snap.id,
                file_path="csrc/kernel.cpp",
                function_name="Kernel::run",
                language="C++",
                cyclomatic_complexity=18,
                max_nesting_depth=4,
                function_lines=80,
                start_line=200,
            ),
            CodeComplexityDetail(
                snapshot_id=snap.id,
                file_path="tests/unit/test_foo.py",
                function_name="test_foo",
                language="Python",
                cyclomatic_complexity=3,
                max_nesting_depth=1,
                function_lines=20,
                start_line=1,
            ),
        ]
        session.add_all(details)

        # 创建测试用户
        user = User(username="testuser", password_hash="x", role="user", email="test@example.com", is_active=True)
        session.add(user)
        await session.commit()
        yield session


@pytest_asyncio.fixture
async def client(test_db, test_engine):
    """Override get_db to use the test database."""
    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # 生成 token
        token = create_access_token({"sub": "testuser", "role": "user"})
        c.headers.update({"Authorization": f"Bearer {token}"})
        yield c
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_files_no_filter(client):
    """文件列表：无过滤返回所有文件（聚合后）。"""
    r = await client.get("/api/v1/code-metrics/files")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3  # 3 unique files
    paths = [item["file_path"] for item in body["items"]]
    assert "vllm_ascend/core/__init__.py" in paths
    assert "csrc/kernel.cpp" in paths
    assert "tests/unit/test_foo.py" in paths


@pytest.mark.asyncio
async def test_list_files_filter_language(client):
    """文件列表：按语言过滤。"""
    r = await client.get("/api/v1/code-metrics/files", params={"language": "Python"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2  # vllm_ascend/core/__init__.py + tests/unit/test_foo.py
    for item in body["items"]:
        assert item["language"] == "Python"


@pytest.mark.asyncio
async def test_list_files_filter_module(client):
    """文件列表：按模块过滤。"""
    r = await client.get("/api/v1/code-metrics/files", params={"module": "csrc"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["file_path"] == "csrc/kernel.cpp"
    assert body["items"][0]["module"] == "csrc"


@pytest.mark.asyncio
async def test_list_files_search(client):
    """文件列表：模糊搜索。"""
    r = await client.get("/api/v1/code-metrics/files", params={"search": "kernel"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert "kernel" in body["items"][0]["file_path"]


@pytest.mark.asyncio
async def test_list_files_aggregation(client):
    """文件列表：聚合字段正确（函数数、总复杂度、最大复杂度）。"""
    r = await client.get("/api/v1/code-metrics/files", params={"search": "__init__"})
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["file_path"] == "vllm_ascend/core/__init__.py"
    assert item["function_count"] == 2  # func_a + func_b
    assert item["total_complexity"] == 30  # 25 + 5
    assert item["max_complexity"] == 25
    assert item["total_function_lines"] == 150  # 120 + 30


@pytest.mark.asyncio
async def test_list_functions_no_filter(client):
    """函数列表：无过滤返回所有函数。"""
    r = await client.get("/api/v1/code-metrics/functions")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    # 默认按复杂度降序
    complexities = [item["cyclomatic_complexity"] for item in body["items"]]
    assert complexities == sorted(complexities, reverse=True)
    assert complexities[0] == 25  # func_a


@pytest.mark.asyncio
async def test_list_functions_filter_file(client):
    """函数列表：按文件路径过滤。"""
    r = await client.get(
        "/api/v1/code-metrics/functions",
        params={"file_path": "vllm_ascend/core/__init__.py"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    for item in body["items"]:
        assert item["file_path"] == "vllm_ascend/core/__init__.py"


@pytest.mark.asyncio
async def test_list_functions_min_complexity(client):
    """函数列表：按最小复杂度过滤。"""
    r = await client.get("/api/v1/code-metrics/functions", params={"min_complexity": 18})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2  # func_a(25) + Kernel::run(18)
    for item in body["items"]:
        assert item["cyclomatic_complexity"] >= 18


@pytest.mark.asyncio
async def test_list_functions_search(client):
    """函数列表：模糊搜索函数名/文件路径。"""
    r = await client.get("/api/v1/code-metrics/functions", params={"search": "Kernel"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["function_name"] == "Kernel::run"


@pytest.mark.asyncio
async def test_drilldown_by_language(client):
    """维度聚合下钻：按语言。"""
    r = await client.get("/api/v1/code-metrics/drilldown", params={"language": "Python"})
    assert r.status_code == 200
    body = r.json()
    assert body["has_data"] is True
    assert body["filter"]["language"] == "Python"
    assert body["loc"] == 8000
    assert body["file_count"] == 2
    assert body["function_count"] == 3  # func_a + func_b + test_foo
    assert body["max_complexity"] == 25
    assert len(body["top_files"]) <= 10
    assert len(body["top_functions"]) <= 10
    # top_functions 第一项应该是 func_a (复杂度 25)
    assert body["top_functions"][0]["function_name"] == "func_a"


@pytest.mark.asyncio
async def test_drilldown_by_module(client):
    """维度聚合下钻：按模块。"""
    r = await client.get("/api/v1/code-metrics/drilldown", params={"module": "csrc"})
    assert r.status_code == 200
    body = r.json()
    assert body["has_data"] is True
    assert body["filter"]["module"] == "csrc"
    assert body["loc"] == 2000
    assert body["file_count"] == 1
    assert body["function_count"] == 1
    assert body["max_complexity"] == 18


@pytest.mark.asyncio
async def test_drilldown_no_data(client, test_db):
    """维度聚合下钻：无快照数据时返回 has_data=False。"""
    # 删除所有快照
    from sqlalchemy import delete
    await test_db.execute(delete(CodeMetricsSnapshot))
    await test_db.commit()
    r = await client.get("/api/v1/code-metrics/drilldown", params={"language": "Python"})
    assert r.status_code == 200
    assert r.json()["has_data"] is False


@pytest.mark.asyncio
async def test_files_pagination(client):
    """文件列表：分页参数。"""
    r = await client.get("/api/v1/code-metrics/files", params={"limit": 2, "offset": 0})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["limit"] == 2
    assert body["offset"] == 0

    r2 = await client.get("/api/v1/code-metrics/files", params={"limit": 2, "offset": 2})
    assert r2.status_code == 200
    body2 = r2.json()
    assert len(body2["items"]) == 1  # 第三页只剩 1 个


@pytest.mark.asyncio
async def test_drilldown_module_loc_case_insensitive(client):
    """维度聚合下钻：module LOC 查找应大小写不敏感（CSRC → csrc）。"""
    # module_loc key 是小写 "csrc"，前端可能传大写 "CSRC"
    r = await client.get("/api/v1/code-metrics/drilldown", params={"module": "CSRC"})
    assert r.status_code == 200
    body = r.json()
    assert body["has_data"] is True
    assert body["loc"] == 2000  # 应该命中 mod_loc_map["csrc"]
    assert body["file_count"] == 1


@pytest.mark.asyncio
async def test_list_files_language_case_sensitive_sql(client):
    """文件列表：language 下推 SQL 后，大小写需匹配存储值（Python/C++）。

    存储的 language 是 "Python"（首字母大写）。SQL WHERE language = 'Python' 能命中；
    传 'python'（全小写）不命中（SQL 大小写敏感，取决于 DB 排序规则）。
    此测试验证传正确大小写能命中。
    """
    r = await client.get("/api/v1/code-metrics/files", params={"language": "Python"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2  # vllm_ascend/core/__init__.py + tests/unit/test_foo.py


@pytest.mark.asyncio
async def test_list_functions_language_pushed_to_sql(client):
    """函数列表：language 过滤下推 SQL，返回的函数语言一致。"""
    r = await client.get("/api/v1/code-metrics/functions", params={"language": "C++"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1  # Kernel::run
    assert body["items"][0]["language"] == "C++"
    assert body["items"][0]["function_name"] == "Kernel::run"
