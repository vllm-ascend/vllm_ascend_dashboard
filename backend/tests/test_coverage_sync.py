"""测试覆盖率同步服务的单元测试。

聚焦纯函数：JS 字面量解析、目录名/硬件/路径解码、SQLite 读取、summary 计算。
无需 MySQL，使用合成 fixture 覆盖正常格式与降级路径（检视意见 #6）。
"""
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.services.coverage_sync import (
    DIM_LABELS_FALLBACK,
    E2ECoverageParser,
    clean_source_path,
    decode_job_dir,
    extract_js_literal,
    module_of,
    parse_hw_from_filename,
    read_covdata_sqlite,
)

# ---------------------------------------------------------------------------
# 合成 coverage.html 样本
# ---------------------------------------------------------------------------
SAMPLE_HTML = """<!DOCTYPE html><html><body>
<script>
    let DATA = [
        {"filepath": "one_card/test_qwen3.py", "test_name": "test_dense", "card_count": 1, "models": ["Qwen/Qwen3-0.6B"], "coverage": {"arch": ["dense"], "feature": [], "parallel": ["TP"], "deploy": ["pd_mix"], "hardware": ["A2"], "quantization": ["BF16"], "graph_mode": ["eager"]}},
        {"filepath": "two_card/test_moe.py", "test_name": "test_moe", "card_count": 2, "models": [], "coverage": {}}
    ];
    const ALLOWED = {"arch": ["dense", "moe"], "feature": ["lora", "mtp"], "parallel": ["TP", "EP"], "deploy": ["pd_mix"], "hardware": ["A2", "A3"], "quantization": ["BF16"], "graph_mode": ["eager", "piecewise"]};
    const DIM_LABELS_JS = {"arch": "Architecture", "feature": "Feature", "parallel": "Parallel", "deploy": "Deploy", "hardware": "Hardware", "quantization": "Quantization", "graph_mode": "Graph Mode"};
</script></body></html>"""


# ---------------------------------------------------------------------------
# extract_js_literal
# ---------------------------------------------------------------------------
class TestExtractJsLiteral:
    def test_extract_array(self):
        data = extract_js_literal(SAMPLE_HTML, "DATA")
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["test_name"] == "test_dense"
        assert data[0]["coverage"]["arch"] == ["dense"]

    def test_extract_object(self):
        allowed = extract_js_literal(SAMPLE_HTML, "ALLOWED")
        assert isinstance(allowed, dict)
        assert "dense" in allowed["arch"]

    def test_extract_dim_labels(self):
        labels = extract_js_literal(SAMPLE_HTML, "DIM_LABELS_JS")
        assert labels["arch"] == "Architecture"

    def test_missing_variable_returns_fallback(self):
        assert extract_js_literal(SAMPLE_HTML, "NOT_EXIST", fallback={"x": 1}) == {"x": 1}

    def test_fallback_when_literal_absent(self):
        # 变量声明存在但无字面量（语法异常）
        bad = "let BROKEN = something();"
        assert extract_js_literal(bad, "BROKEN", fallback=None) is None

    def test_string_with_brackets(self):
        # 字符串内含 ] / } 不应误判括号结束
        content = 'let DATA = [{"a": "x]y}z", "b": 1}];'
        data = extract_js_literal(content, "DATA")
        assert data == [{"a": "x]y}z", "b": 1}]

    def test_trailing_comma(self):
        content = "let DATA = [1, 2, 3,];"
        data = extract_js_literal(content, "DATA")
        assert data == [1, 2, 3]


# ---------------------------------------------------------------------------
# decode_job_dir
# ---------------------------------------------------------------------------
class TestDecodeJobDir:
    def test_basic(self):
        r = decode_job_dir("tests__e2e__pull_request__one_card___310p__test_x")
        assert r["test_path"] == "tests/e2e/pull_request/one_card/_310p/test_x"
        assert r["test_type"] == "e2e"
        assert r["test_func"] is None

    def test_ut_type(self):
        r = decode_job_dir("tests__ut__attention__a2__test_mla")
        assert r["test_type"] == "ut"
        assert r["test_path"] == "tests/ut/attention/a2/test_mla"

    def test_test_func_suffix(self):
        r = decode_job_dir("tests__e2e__pull_request__two_card__test_flashcomm.py--test_qwen3_dense_fc1_tp2")
        assert r["test_func"] == "test_qwen3_dense_fc1_tp2"
        assert r["test_path"] == "tests/e2e/pull_request/two_card/test_flashcomm.py"

    def test_triple_underscore(self):
        # ___ -> /_ （目录名以 _ 开头的场景）
        r = decode_job_dir("a__b___c__d")
        assert r["test_path"] == "a/b/_c/d"


# ---------------------------------------------------------------------------
# parse_hw_from_filename
# ---------------------------------------------------------------------------
class TestParseHw:
    def test_a2(self):
        assert parse_hw_from_filename("coverage.linux-aarch64-a2b3-1-ngmjb-runner-x-workflow.pid1.X.Y") == ("A2", 1)

    def test_a3_two_card(self):
        assert parse_hw_from_filename("coverage.linux-aarch64-a3-2-7jx9v-runner-x-workflow.pid2.X.Y") == ("A3", 2)

    def test_a3_four_card(self):
        assert parse_hw_from_filename("coverage.linux-aarch64-a3-4-hwj74-runner-x-workflow.pid3.X.Y") == ("A3", 4)

    def test_310p(self):
        assert parse_hw_from_filename("coverage.linux-aarch64-310p-1-cvgd7-runner-x-workflow.pid4.X.Y") == ("310P", 1)

    def test_unknown(self):
        assert parse_hw_from_filename("notmatching") == ("unknown", 0)


# ---------------------------------------------------------------------------
# clean_source_path / module_of
# ---------------------------------------------------------------------------
class TestPathHelpers:
    def test_clean_github_actions_prefix(self):
        assert clean_source_path("/__w/vllm-ascend/vllm-ascend/vllm_ascend/platform.py") == "vllm_ascend/platform.py"

    def test_clean_already_relative(self):
        assert clean_source_path("vllm_ascend/patch/x.py") == "vllm_ascend/patch/x.py"

    def test_clean_fallback_prefix(self):
        assert clean_source_path("/some/other/path/vllm_ascend/core/y.py") == "vllm_ascend/core/y.py"

    def test_module_top(self):
        assert module_of("vllm_ascend/platform.py") == "vllm_ascend"

    def test_module_nested(self):
        assert module_of("vllm_ascend/patch/platform/z.py") == "vllm_ascend/patch"


# ---------------------------------------------------------------------------
# E2ECoverageParser decorate / summary
# ---------------------------------------------------------------------------
class TestE2EDecorate:
    def test_marked(self):
        t = {"coverage": {"arch": ["dense"], "feature": []}}
        assert E2ECoverageParser._decorate(t)["is_marked"] is True

    def test_unmarked_empty_coverage(self):
        t = {"coverage": {}}
        assert E2ECoverageParser._decorate(t)["is_marked"] is False

    def test_unmarked_all_empty_arrays(self):
        t = {"coverage": {"arch": [], "feature": []}}
        assert E2ECoverageParser._decorate(t)["is_marked"] is False

    def test_summary(self):
        tests = [
            {"card_count": 1, "is_marked": True},
            {"card_count": 1, "is_marked": False},
            {"card_count": 2, "is_marked": False},
        ]
        s = E2ECoverageParser._build_summary(tests)
        assert s["total_tests"] == 3
        assert s["marked_tests"] == 1
        assert s["marked_ratio"] == round(1 / 3, 4)
        assert s["by_card"] == {"1": 2, "2": 1}


# ---------------------------------------------------------------------------
# E2ECoverageParser.parse（合成 HTML 文件 + mock cache）
# ---------------------------------------------------------------------------
class TestE2EParse:
    def test_parse_synthetic_html(self, tmp_path: Path, monkeypatch):
        html_file = tmp_path / "tests/e2e/coverage.html"
        html_file.parent.mkdir(parents=True)
        html_file.write_text(SAMPLE_HTML, encoding="utf-8")

        cache = MagicMock()
        cache.cache_dir = tmp_path
        cache.get_latest_commit.return_value = "abc1234"

        parser = E2ECoverageParser()
        monkeypatch.setattr("app.services.coverage_sync.get_github_cache", lambda: cache)

        result = parser.parse()
        assert result["summary"]["total_tests"] == 2
        assert result["summary"]["marked_tests"] == 1
        assert result["repo_commit"] == "abc1234"
        assert result["taxonomy"]["arch"] == ["dense", "moe"]
        assert result["dim_labels"]["hardware"] == "Hardware"
        assert result["tests"][0]["is_marked"] is True
        assert result["tests"][1]["is_marked"] is False
        assert result["source_file_hash"].startswith("sha256:")

    def test_parse_missing_html_raises(self, tmp_path: Path, monkeypatch):
        cache = MagicMock()
        cache.cache_dir = tmp_path
        monkeypatch.setattr("app.services.coverage_sync.get_github_cache", lambda: cache)
        parser = E2ECoverageParser()
        with pytest.raises(FileNotFoundError):
            parser.parse()

    def test_dim_labels_fallback(self, monkeypatch):
        # DIM_LABELS_JS 缺失时用兜底
        html = '<script>let DATA = [{"filepath":"a","test_name":"t","card_count":1,"models":[],"coverage":{"arch":["dense"]}}];</script>'
        tmp = Path(tempfile.mkdtemp())
        (tmp / "tests/e2e").mkdir(parents=True)
        (tmp / "tests/e2e/coverage.html").write_text(html, encoding="utf-8")
        cache = MagicMock()
        cache.cache_dir = tmp
        cache.get_latest_commit.return_value = None
        monkeypatch.setattr("app.services.coverage_sync.get_github_cache", lambda: cache)
        result = E2ECoverageParser().parse()
        assert result["dim_labels"] == DIM_LABELS_FALLBACK


# ---------------------------------------------------------------------------
# read_covdata_sqlite（合成 SQLite）
# ---------------------------------------------------------------------------
def _make_covdata(path: Path, *, files: list[str], arcs: int, when: str = "2026-07-22 19:50:05",
                  version: str = "7.15.2") -> None:
    con = sqlite3.connect(str(path))
    con.executescript(
        "CREATE TABLE file (id integer primary key, path text, unique(path));"
        "CREATE TABLE arc (file_id integer, from_line integer, to_line integer);"
        "CREATE TABLE meta (key text primary key, value text);"
        "CREATE TABLE line_bits (file_id integer, context_id integer, numbits blob);"
        "CREATE TABLE context (id integer primary key, context text);"
    )
    for i, f in enumerate(files, 1):
        con.execute("INSERT INTO file(id, path) VALUES (?, ?)", (i, f))
    for _ in range(arcs):
        con.execute("INSERT INTO arc(file_id, from_line, to_line) VALUES (1, 1, 2)")
    con.execute("INSERT INTO meta(key, value) VALUES ('version', ?)", (version,))
    con.execute("INSERT INTO meta(key, value) VALUES ('when', ?)", (when,))
    con.execute("INSERT INTO meta(key, value) VALUES ('has_arcs', '1')")
    con.execute("INSERT INTO meta(key, value) VALUES ('sys_argv', 'pytest test_x.py')")
    con.commit()
    con.close()


class TestReadCovdata:
    def test_normal(self, tmp_path: Path):
        p = tmp_path / "c.covdata"
        _make_covdata(p, files=["/__w/vllm-ascend/vllm-ascend/vllm_ascend/platform.py"], arcs=5)
        stats = read_covdata_sqlite(p)
        assert stats is not None
        assert stats["arcs"] == 5
        assert stats["files"] == ["vllm_ascend/platform.py"]
        assert stats["when"] == "2026-07-22 19:50:05"
        assert stats["version"] == "7.15.2"

    def test_corrupt_returns_none(self, tmp_path: Path):
        p = tmp_path / "broken.covdata"
        p.write_bytes(b"not a sqlite database")
        assert read_covdata_sqlite(p) is None
