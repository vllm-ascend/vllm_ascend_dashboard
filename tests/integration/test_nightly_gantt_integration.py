"""集成测试：NightlyGanttService.get_gantt_data 完整流程

用 Fake GitHubClient 替代真实 API，验证 _locate_run → get_job_list → _build_rows → KPI 组装的端到端逻辑，
覆盖正常流程、未找到 run（对应 404）、非法 hardware（对应 400）、DB 缓存命中跳过翻页等场景。
"""
from datetime import UTC, datetime

import pytest

from nightly_gantt.nightly_gantt_service import NightlyGanttService


class FakeGitHubClient:
    """替代真实 GitHubClient，记录调用次数/翻页以验证快路径与回退。"""

    def __init__(self, runs=None, jobs=None, runs_pages=None):
        self.owner = "vllm-project"
        self.repo = "vllm-ascend"
        self._runs = runs or []
        self._runs_pages = runs_pages  # list[list]，优先用于多页翻页测试
        self._jobs = jobs or []
        self.calls = {"workflow_runs": 0, "job_list": 0, "pages_fetched": []}

    async def get_workflow_runs(self, workflow_id_or_name=None, per_page=100, page=1, **kw):
        self.calls["workflow_runs"] += 1
        self.calls["pages_fetched"].append(page)
        if self._runs_pages is not None:
            return self._runs_pages[page - 1] if page <= len(self._runs_pages) else []
        return self._runs

    async def get_job_list(self, run_id):
        self.calls["job_list"] += 1
        return self._jobs

    async def close(self):
        pass


def _make_run(run_number=15540, run_id=999):
    return {
        "id": run_id,
        "run_number": run_number,
        "status": "completed",
        "conclusion": "success",
        "created_at": "2026-03-23T08:00:00Z",
        "updated_at": "2026-03-23T10:00:00Z",
        "html_url": "https://github.com/vllm-project/vllm-ascend/actions/runs/999",
    }


def _make_job(name, conclusion="success", started="2026-03-23T08:00:00Z",
              completed="2026-03-23T08:30:00Z", job_id=100, run_id=999):
    return {
        "name": name,
        "conclusion": conclusion,
        "started_at": started,
        "completed_at": completed,
        "id": job_id,
        "run_id": run_id,
    }


class _FakeResult:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class FakeDB:
    """模拟 AsyncSession，execute 返回含目标 CIResult；ci_result=None 表示未命中。"""

    def __init__(self, ci_result=None):
        self._ci_result = ci_result

    async def execute(self, stmt):
        return _FakeResult(self._ci_result)


class FakeCIResult:
    def __init__(self, run_id=888):
        self.run_id = run_id
        self.status = "completed"
        self.conclusion = "success"
        self.started_at = datetime(2026, 3, 23, 8, 0, 0, tzinfo=UTC)
        self.completed_at = datetime(2026, 3, 23, 10, 0, 0, tzinfo=UTC)
        self.duration_seconds = 7200


async def test_get_gantt_data_normal_flow():
    """正常流程：基础设施过滤 + 分类 + KPI + 排序 + run_meta 组装。"""
    run = _make_run()
    jobs = [
        _make_job("Parse trigger", job_id=1),  # 基础设施，应过滤
        _make_job("multi-node (main, DeepSeek-V3, config.yaml)", job_id=2),
        _make_job("single-node (main, tests/e2e/test_lm_eval.py, config.yaml)",
                  conclusion="failure", job_id=3),
    ]
    client = FakeGitHubClient(runs=[run], jobs=jobs)
    svc = NightlyGanttService(db=None, github_client=client)
    data = await svc.get_gantt_data(run_number=15540, hardware="a3")

    assert data["run_number"] == 15540
    assert data["run_id"] == 999
    assert data["hardware"] == "A3"
    assert data["workflow_file"] == "schedule_nightly_test_a3.yaml"
    assert data["workflow_display"] == "Nightly-A3"
    # 基础设施过滤后剩 2 个用例
    assert data["kpi"]["total"] == 2
    assert data["kpi"]["ok"] == 1
    assert data["kpi"]["err"] == 1
    # run_meta 透传
    assert data["run_meta"]["status"] == "completed"
    assert data["run_meta"]["html_url"].endswith("/runs/999")
    # rows 排序：Multi-node 在 Single-node 前
    assert data["rows"][0]["phase"] == "Multi-node"
    assert data["rows"][1]["phase"] == "Single-node"
    # pytest 路径提取用例名
    assert data["rows"][1]["name"] == "test_lm_eval"
    # phases 分组
    assert len(data["phases"]["Multi-node"]) == 1
    assert len(data["phases"]["Single-node"]) == 1
    assert len(data["phases"]["Double-node"]) == 0
    # 翻页 + jobs 各调用 1 次
    assert client.calls["workflow_runs"] == 1
    assert client.calls["job_list"] == 1


async def test_get_gantt_data_run_not_found_raises_runtime():
    """未找到 run_number 应抛 RuntimeError（API 层转 404）。"""
    client = FakeGitHubClient(runs=[], jobs=[])
    svc = NightlyGanttService(db=None, github_client=client)
    with pytest.raises(RuntimeError, match="not found"):
        await svc.get_gantt_data(run_number=99999, hardware="a3")


async def test_get_gantt_data_invalid_hardware_raises_value():
    """非法 hardware 应抛 ValueError（API 层转 400）。"""
    client = FakeGitHubClient()
    svc = NightlyGanttService(db=None, github_client=client)
    with pytest.raises(ValueError, match="Unsupported hardware"):
        await svc.get_gantt_data(run_number=15540, hardware="a4")


async def test_get_gantt_data_db_cache_hit_skips_github_runs():
    """DB 命中应跳过 get_workflow_runs，但仍调 get_job_list 拉 jobs。"""
    run = _make_run()
    jobs = [_make_job("multi-node (main, X, c.yaml)", job_id=2)]
    client = FakeGitHubClient(runs=[run], jobs=jobs)
    db = FakeDB(ci_result=FakeCIResult(run_id=888))

    svc = NightlyGanttService(db=db, github_client=client)
    data = await svc.get_gantt_data(run_number=15540, hardware="a3")

    # run_id 来自 DB 缓存
    assert data["run_id"] == 888
    # 未调 get_workflow_runs（DB 命中快路径）
    assert client.calls["workflow_runs"] == 0
    # 仍调 get_job_list 拉 jobs
    assert client.calls["job_list"] == 1
    assert data["kpi"]["total"] == 1


async def test_get_gantt_data_db_miss_falls_back_to_github():
    """DB 未命中（scalar_one_or_none 返回 None）应回退 GitHub API 翻页查找。"""
    run = _make_run()
    jobs = [_make_job("multi-node (main, X, c.yaml)", job_id=2)]
    client = FakeGitHubClient(runs=[run], jobs=jobs)
    db = FakeDB(ci_result=None)  # DB 未命中

    svc = NightlyGanttService(db=db, github_client=client)
    data = await svc.get_gantt_data(run_number=15540, hardware="a3")

    # DB 未命中 -> 回退 GitHub，run_id 来自 GitHub API
    assert data["run_id"] == 999
    assert client.calls["workflow_runs"] == 1
    assert client.calls["job_list"] == 1


async def test_get_gantt_data_pagination_multi_page():
    """第一页无匹配、第二页命中，验证翻页查找逻辑。"""
    target = _make_run(run_number=15540, run_id=999)
    other = _make_run(run_number=15539, run_id=888)
    jobs = [_make_job("multi-node (main, X, c.yaml)", job_id=2)]
    # 第一页只有 15539，第二页才是 15540
    client = FakeGitHubClient(runs_pages=[[other], [target]], jobs=jobs)

    svc = NightlyGanttService(db=None, github_client=client)
    data = await svc.get_gantt_data(run_number=15540, hardware="a3")

    assert data["run_id"] == 999
    # 翻了 2 页才命中
    assert client.calls["workflow_runs"] == 2
    assert client.calls["pages_fetched"] == [1, 2]


async def test_get_gantt_data_empty_jobs():
    """run 存在但无 jobs（空列表），应返回空 rows 与全 0 KPI。"""
    run = _make_run()
    client = FakeGitHubClient(runs=[run], jobs=[])

    svc = NightlyGanttService(db=None, github_client=client)
    data = await svc.get_gantt_data(run_number=15540, hardware="a3")

    assert data["run_id"] == 999
    assert data["kpi"]["total"] == 0
    assert data["kpi"]["ok"] == 0
    assert data["kpi"]["err"] == 0
    assert data["kpi"]["span_ms"] == 0
    assert data["rows"] == []
    assert data["kpi"]["ok_rate"] == 0.0
