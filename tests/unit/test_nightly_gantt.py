"""单元测试：Nightly 用例执行甘特图服务

覆盖 nightly_gantt_service 的纯函数与 _build_rows 静态方法：
- classify_job：阶段分类
- extract_display_name：用例名提取
- is_infra_job：基础设施 Job 过滤
- format_duration：耗时格式化
- _build_rows：jobs 过滤 + 分类 + 排序 + 时间转换 + 状态判定

不依赖数据库或网络，全部为纯函数测试。
"""
from datetime import timedelta

from nightly_gantt.nightly_gantt_service import (
    NightlyGanttService,
    _parse_iso,
    classify_job,
    extract_display_name,
    format_duration,
    is_infra_job,
)

# ============================================================================
# classify_job
# ============================================================================

def test_classify_multi_node():
    assert classify_job("multi-node (main, DeepSeek-V3, config.yaml)") == "Multi-node"


def test_classify_double_node():
    assert classify_job("double-node (main, Qwen3-8B, config.yaml)") == "Double-node"


def test_classify_single_node():
    assert classify_job("single-node (main, Llama, config.yaml)") == "Single-node"


def test_classify_non_case_job():
    """基础设施或无法分类的 job 返回 None。"""
    assert classify_job("Parse trigger") is None
    assert classify_job("Build nightly") is None
    assert classify_job("some-other-job") is None


def test_classify_case_insensitive():
    """分类对大小写不敏感（与 nightly_report.py 一致）。"""
    assert classify_job("MULTI-NODE (x)") == "Multi-node"
    assert classify_job("Single-Node (x)") == "Single-node"


# ============================================================================
# extract_display_name
# ============================================================================

def test_extract_name_with_paren_model():
    """括号内第二个参数为模型名时直接返回。"""
    assert extract_display_name("multi-node (main, DeepSeek-V3_2-W8A8-EP, config.yaml)") == "DeepSeek-V3_2-W8A8-EP"


def test_extract_name_with_pytest_path():
    """第二参数为 pytest 路径时取文件名并去 .py 后缀。"""
    name = "single-node (main, tests/e2e/test_lm_eval.py, config.yaml)"
    assert extract_display_name(name) == "test_lm_eval"


def test_extract_name_no_paren():
    """无括号时原样返回。"""
    assert extract_display_name("plain-job-name") == "plain-job-name"


def test_extract_name_insufficient_parts():
    """括号内参数不足 2 个时回退为原 name。"""
    assert extract_display_name("multi-node (only)") == "multi-node (only)"


# ============================================================================
# is_infra_job
# ============================================================================

def test_is_infra_job_matches_keywords():
    """命中任一基础设施关键词即判定为基础设施 Job。"""
    assert is_infra_job("Parse trigger (nightly)")
    assert is_infra_job("Export global env vars")
    assert is_infra_job("Build nightly image")
    assert is_infra_job("clear-pre-logs")
    assert is_infra_job("Remove node taints")
    assert is_infra_job("Merge benchmark results")


def test_is_infra_job_case_insensitive():
    """关键词匹配大小写不敏感。"""
    assert is_infra_job("PARSE TRIGGER")
    assert is_infra_job("BUILD NIGHTLY")


def test_is_infra_job_not_matched():
    """用例 Job 不应被误判为基础设施。"""
    assert not is_infra_job("multi-node (main, DeepSeek-V3, config.yaml)")
    assert not is_infra_job("single-node (main, tests/e2e/test_lm_eval.py)")


# ============================================================================
# format_duration
# ============================================================================

def test_format_duration_zero_or_negative():
    assert format_duration(timedelta(0)) == "—"
    assert format_duration(timedelta(seconds=-5)) == "—"


def test_format_duration_seconds_only():
    assert format_duration(timedelta(seconds=5)) == "5s"
    assert format_duration(timedelta(seconds=59)) == "59s"


def test_format_duration_minutes():
    """m>0 且 s==0 时只返回 Xm；s>0 时返回 Xm Ys（与 nightly_report.py 一致）。"""
    assert format_duration(timedelta(minutes=5)) == "5m"
    assert format_duration(timedelta(minutes=5, seconds=30)) == "5m30s"


def test_format_duration_hours():
    assert format_duration(timedelta(hours=1, minutes=23)) == "1h23m"
    assert format_duration(timedelta(hours=2, minutes=0, seconds=5)) == "2h0m"


# ============================================================================
# _build_rows
# ============================================================================

def _make_job(
    name: str,
    started_at: str = "2026-03-23T08:00:00Z",
    completed_at: str = "2026-03-23T08:30:00Z",
    conclusion: str = "success",
    job_id: int = 100,
    run_id: int = 999,
) -> dict:
    """构造 GitHub API job dict。"""
    return {
        "name": name,
        "started_at": started_at,
        "completed_at": completed_at,
        "conclusion": conclusion,
        "id": job_id,
        "run_id": run_id,
    }


def test_build_rows_filters_infra_and_unclassified():
    """基础设施 Job 与无法分类的 Job 应被过滤。"""
    jobs = [
        _make_job("Parse trigger", job_id=1),
        _make_job("Build nightly", job_id=2),
        _make_job("unknown-job", job_id=3),
        _make_job("single-node (main, Model-A, config.yaml)", job_id=4),
    ]
    rows = NightlyGanttService._build_rows(jobs)
    assert len(rows) == 1
    assert rows[0]["name"] == "Model-A"
    assert rows[0]["phase"] == "Single-node"


def test_build_rows_skips_skipped_conclusion():
    """conclusion=skipped 的用例应被跳过。"""
    jobs = [
        _make_job("single-node (main, Skipped-Case, config.yaml)", conclusion="skipped", job_id=1),
        _make_job("single-node (main, OK-Case, config.yaml)", conclusion="success", job_id=2),
    ]
    rows = NightlyGanttService._build_rows(jobs)
    assert len(rows) == 1
    assert rows[0]["name"] == "OK-Case"


def test_build_rows_skips_missing_timestamps():
    """缺起止时间的 job 应被跳过。"""
    jobs = [
        {"name": "single-node (main, NoTime, config.yaml)", "conclusion": "success", "id": 1, "run_id": 9},
        _make_job("single-node (main, HasTime, config.yaml)", job_id=2),
    ]
    rows = NightlyGanttService._build_rows(jobs)
    assert len(rows) == 1
    assert rows[0]["name"] == "HasTime"


def test_build_rows_status_ok_and_err():
    """success -> ok，其它 conclusion -> err。"""
    jobs = [
        _make_job("multi-node (main, Pass-Case, c.yaml)", conclusion="success", job_id=1),
        _make_job("multi-node (main, Fail-Case, c.yaml)", conclusion="failure", job_id=2),
        _make_job("multi-node (main, Cancel-Case, c.yaml)", conclusion="cancelled", job_id=3),
    ]
    rows = NightlyGanttService._build_rows(jobs)
    by_name = {r["name"]: r for r in rows}
    assert by_name["Pass-Case"]["status"] == "ok"
    assert by_name["Fail-Case"]["status"] == "err"
    assert by_name["Cancel-Case"]["status"] == "err"


def test_build_rows_sorts_by_phase_then_start():
    """先按阶段顺序（Multi > Double > Single），同阶段按开始时间升序。"""
    jobs = [
        # Single-node 早开始
        _make_job("single-node (main, S-Early, c.yaml)",
                  started_at="2026-03-23T08:00:00Z", completed_at="2026-03-23T08:10:00Z", job_id=1),
        # Multi-node 晚开始
        _make_job("multi-node (main, M-Late, c.yaml)",
                  started_at="2026-03-23T09:00:00Z", completed_at="2026-03-23T09:30:00Z", job_id=2),
        # Multi-node 早开始
        _make_job("multi-node (main, M-Early, c.yaml)",
                  started_at="2026-03-23T08:30:00Z", completed_at="2026-03-23T09:00:00Z", job_id=3),
        # Double-node
        _make_job("double-node (main, D-1, c.yaml)",
                  started_at="2026-03-23T08:15:00Z", completed_at="2026-03-23T08:45:00Z", job_id=4),
    ]
    rows = NightlyGanttService._build_rows(jobs)
    phases = [r["phase"] for r in rows]
    names = [r["name"] for r in rows]
    assert phases == ["Multi-node", "Multi-node", "Double-node", "Single-node"]
    # Multi-node 内部按开始时间升序：M-Early(08:30) 在 M-Late(09:00) 前
    assert names == ["M-Early", "M-Late", "D-1", "S-Early"]


def test_build_rows_beijing_time_conversion():
    """UTC ISO 字符串应正确转换为北京时间 HH:MM:SS 与 UTC 毫秒戳。"""
    jobs = [
        _make_job("single-node (main, Time-Check, c.yaml)",
                  started_at="2026-03-23T00:00:00Z",  # UTC 00:00 = 北京 08:00
                  completed_at="2026-03-23T01:00:00Z",  # UTC 01:00 = 北京 09:00
                  job_id=1),
    ]
    rows = NightlyGanttService._build_rows(jobs)
    r = rows[0]
    assert r["start_bj"] == "08:00:00"
    assert r["end_bj"] == "09:00:00"
    assert r["duration"] == "1h0m"
    assert r["duration_seconds"] == 3600
    # start_ms/end_ms 为 UTC 毫秒戳，且 end_ms - start_ms == 3600*1000
    assert r["end_ms"] - r["start_ms"] == 3600 * 1000


def test_build_rows_constructs_job_url():
    """应构造 GitHub job 详情页 URL。"""
    jobs = [_make_job("single-node (main, X, c.yaml)", job_id=12345, run_id=67890)]
    rows = NightlyGanttService._build_rows(jobs)
    assert rows[0]["job_url"] == "https://github.com/vllm-project/vllm-ascend/actions/runs/67890/job/12345"


def test_build_rows_empty_input():
    """空 jobs 列表应返回空 rows。"""
    assert NightlyGanttService._build_rows([]) == []


def test_parse_iso_handles_z_suffix():
    """_parse_iso 应处理 Z 后缀并返回带时区 datetime。"""
    dt = _parse_iso("2026-03-23T08:00:00Z")
    assert dt.year == 2026 and dt.month == 3 and dt.day == 23
    assert dt.hour == 8
    # 应为 UTC 时区
    assert dt.utcoffset().total_seconds() == 0
