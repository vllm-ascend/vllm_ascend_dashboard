"""
VersionQualityFileStore 和 HTML 净化/提取的单元测试。

覆盖 P0 安全修复：
- 路径遍历防护（report_id 含 ../, /, \\ 等）
- HTML 净化（<script>/on*/javascript: 移除）
- HTML 提取容错（markdown 代码块 / 直接输出 / 嵌入输出 / 截断检测）
"""
import asyncio

import pytest

from app.services.version_quality_file_store import (
    VersionQualityFileStore,
    _sanitize_component,
)
from app.services.version_quality_service import (
    VersionQualityService,
    _sanitize_html,
)

# =========================================================================
# VersionQualityFileStore — 路径遍历防护
# =========================================================================


class TestPathTraversalProtection:
    """P0-1: report_id 路径遍历漏洞修复验证"""

    def setup_method(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.store = VersionQualityFileStore(base_dir=self.tmpdir)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @pytest.mark.parametrize("malicious_id", [
        "../../etc/passwd",
        "..\\..\\windows\\win",
        "../../../config",
        "foo/../../bar",
        "foo/../../../bar",
        "/etc/passwd",
        "..%2f..%2fconfig",
    ])
    def test_get_report_meta_rejects_traversal(self, malicious_id):
        """get_report_meta 不应读取 base_dir 之外的文件"""
        result = asyncio.run(self.store.get_report_meta(malicious_id))
        assert result is None

    @pytest.mark.parametrize("malicious_id", [
        "../../etc/passwd",
        "../../../config",
        "foo/../../../bar",
    ])
    def test_delete_report_rejects_traversal(self, malicious_id):
        """delete_report 不应删除 base_dir 之外的文件"""
        result = asyncio.run(self.store.delete_report(malicious_id))
        assert result is False

    @pytest.mark.parametrize("malicious_id", [
        "../../etc/passwd",
        "../../../config",
    ])
    def test_get_html_path_rejects_traversal(self, malicious_id):
        """get_html_path 不应返回 base_dir 之外的路径"""
        result = asyncio.run(self.store.get_html_path(malicious_id))
        assert result is None

    @pytest.mark.parametrize("malicious_id", [
        "../../etc/passwd",
        "../../../config",
    ])
    def test_get_report_html_rejects_traversal(self, malicious_id):
        """get_report_html 不应读取 base_dir 之外的文件"""
        result = asyncio.run(self.store.get_report_html(malicious_id))
        assert result is None

    def test_valid_report_id_accepted(self):
        """合法 report_id 应被接受"""
        # 保存一个合法报告
        result = asyncio.run(self.store.save_report(
            base_tag="v0.1.0",
            head_tag="v0.2.0",
            html_content="<html></html>",
            metadata={"llm_provider": "test"},
        ))
        report_id = result["report_id"]
        # 读取应成功
        meta = asyncio.run(self.store.get_report_meta(report_id))
        assert meta is not None
        assert meta["base_tag"] == "v0.1.0"
        assert meta["head_tag"] == "v0.2.0"

    def test_report_id_with_spaces_rejected(self):
        """含空格的 report_id 应被拒绝"""
        result = asyncio.run(self.store.get_report_meta("foo bar"))
        assert result is None

    def test_report_id_with_null_byte_rejected(self):
        """含 null byte 的 report_id 应被拒绝"""
        result = asyncio.run(self.store.get_report_meta("foo\x00bar"))
        assert result is None


# =========================================================================
# VersionQualityFileStore — CRUD 操作
# =========================================================================


class TestFileStoreCRUD:

    def setup_method(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.store = VersionQualityFileStore(base_dir=self.tmpdir)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_and_read_report(self):
        """保存后能正确读取元数据和 HTML"""
        html = "<!DOCTYPE html><html><body>test report</body></html>"
        result = asyncio.run(self.store.save_report(
            base_tag="base_v1",
            head_tag="head_v1",
            html_content=html,
            metadata={"llm_provider": "openai", "total_commits": 42},
        ))
        report_id = result["report_id"]

        # 验证元数据
        meta = asyncio.run(self.store.get_report_meta(report_id))
        assert meta is not None
        assert meta["base_tag"] == "base_v1"
        assert meta["head_tag"] == "head_v1"
        assert meta["total_commits"] == 42
        assert meta["llm_provider"] == "openai"

        # 验证 HTML
        html_content = asyncio.run(self.store.get_report_html(report_id))
        assert html_content == html

    def test_list_reports_sorted_by_time(self):
        """list_reports 按生成时间倒序排列"""
        asyncio.run(self.store.save_report("a", "b", "<html></html>", {}))
        asyncio.run(self.store.save_report("c", "d", "<html></html>", {}))

        reports = asyncio.run(self.store.list_reports())
        assert len(reports) >= 2
        # 验证倒序
        assert reports[0]["generated_at"] >= reports[1]["generated_at"]

    def test_delete_report(self):
        """删除报告后无法读取"""
        result = asyncio.run(self.store.save_report("x", "y", "<html></html>", {}))
        report_id = result["report_id"]

        deleted = asyncio.run(self.store.delete_report(report_id))
        assert deleted is True

        # 删除后读取应返回 None
        assert asyncio.run(self.store.get_report_meta(report_id)) is None
        assert asyncio.run(self.store.get_report_html(report_id)) is None

    def test_delete_nonexistent_returns_false(self):
        """删除不存在的报告返回 False"""
        deleted = asyncio.run(self.store.delete_report("nonexistent_report_id"))
        assert deleted is False

    def test_find_report_by_tags(self):
        """find_report_by_tags 按前缀查找最新报告"""
        asyncio.run(self.store.save_report("v1", "v2", "<html></html>", {}))
        asyncio.run(self.store.save_report("v1", "v2", "<html></html>", {}))
        asyncio.run(self.store.save_report("v3", "v4", "<html></html>", {}))

        # 查找 v1→v2 的最新报告
        found = asyncio.run(self.store.find_report_by_tags("v1", "v2"))
        assert found is not None
        assert found["base_tag"] == "v1"
        assert found["head_tag"] == "v2"

        # 不存在的组合
        not_found = asyncio.run(self.store.find_report_by_tags("v1", "v999"))
        assert not_found is None


# =========================================================================
# _sanitize_html — HTML 净化（P0-3 XSS 防护）
# =========================================================================


class TestSanitizeHtml:

    def test_removes_script_tag(self):
        """<script> 标签应被完全移除"""
        html_content = '<p>safe</p><script>alert("xss")</script><p>more</p>'
        result = _sanitize_html(html_content)
        assert "<script" not in result.lower()
        assert "alert" not in result
        assert "safe" in result
        assert "more" in result

    def test_removes_iframe_tag(self):
        """<iframe> 标签应被移除"""
        html_content = '<p>safe</p><iframe src="evil.com"></iframe><p>end</p>'
        result = _sanitize_html(html_content)
        assert "<iframe" not in result.lower()

    def test_removes_on_event_attributes(self):
        """on* 事件属性应被移除"""
        html_content = '<img src="img.png" onerror="alert(1)" onload="steal()">'
        result = _sanitize_html(html_content)
        assert "onerror" not in result.lower()
        assert "onload" not in result.lower()
        assert "src" in result  # 安全属性应保留

    def test_blocks_javascript_uri(self):
        """javascript: URI 应被移除"""
        html_content = '<a href="javascript:alert(1)">click</a>'
        result = _sanitize_html(html_content)
        assert "javascript:" not in result.lower()

    def test_blocks_vbscript_uri(self):
        """vbscript: URI 应被移除"""
        html_content = '<a href="vbscript:msgbox(1)">click</a>'
        result = _sanitize_html(html_content)
        assert "vbscript:" not in result.lower()

    def test_preserves_safe_html(self):
        """安全 HTML 应被保留"""
        html_content = '<div class="card"><p style="color:red">text</p></div>'
        result = _sanitize_html(html_content)
        assert "card" in result
        assert "color:red" in result or "color: red" in result
        assert "text" in result

    def test_preserves_href_https(self):
        """安全的 https: href 应被保留"""
        html_content = '<a href="https://github.com/safe">link</a>'
        result = _sanitize_html(html_content)
        assert "github.com" in result

    def test_empty_input(self):
        """空输入应返回空字符串"""
        assert _sanitize_html("") == ""

    def test_removes_object_embed(self):
        """<object>/<embed> 标签应被移除"""
        html_content = '<p>safe</p><object data="evil"></object><embed src="evil">'
        result = _sanitize_html(html_content)
        assert "<object" not in result.lower()
        assert "<embed" not in result.lower()

    def test_style_content_not_escaped(self):
        """<style> 内容（CSS）不应被 html.escape 转义（P0-3 CSS 回归修复）"""
        css = "body > div { color: red; } .card > .title { font-weight: bold; }"
        html_content = f"<style>{css}</style>"
        result = _sanitize_html(html_content)
        assert "<style>" in result
        assert "</style>" in result
        # CSS 子选择器 > 应保持原样，不被转义为 &gt;
        assert "body > div" in result
        assert ".card > .title" in result
        assert "&gt;" not in result

    def test_style_with_ampersand_preserved(self):
        """<style> 中的 & 应保持原样（CSS 不转义）"""
        html_content = "<style>a::after { content: 'x & y'; }</style>"
        result = _sanitize_html(html_content)
        assert "& y" in result
        assert "&amp; y" not in result

    def test_text_outside_style_still_escaped(self):
        """<style> 外的文本仍应被转义"""
        html_content = "<style>body > div { color: red; }</style><p>1 < 2 & 3</p>"
        result = _sanitize_html(html_content)
        # CSS 内 > 保持原样
        assert "body > div" in result
        # 普通文本中 < 和 & 被转义
        assert "1 &lt; 2" in result

    def test_javascript_uri_with_tab_blocked(self):
        """javascript: URI 含 Tab 不应 bypass（非阻断1 修复）"""
        html_content = '<a href="java\tscript:alert(1)">click</a>'
        result = _sanitize_html(html_content)
        assert "javascript" not in result.lower() or "alert" not in result


# =========================================================================
# VersionQualityService._extract_html — HTML 提取容错
# =========================================================================


class TestExtractHtml:
    """_extract_html 的各种 LLM 输出格式处理"""

    def _get_service(self):
        """创建一个不依赖 DB 的测试用 service 实例"""
        # 直接实例化，跳过 __init__ 的 DB 依赖
        service = VersionQualityService.__new__(VersionQualityService)
        return service

    def test_extract_from_markdown_codeblock(self):
        """从 ```html ... ``` 代码块提取"""
        service = self._get_service()
        content = 'Here is the report:\n```html\n<!DOCTYPE html><html><body>report</body></html>\n```'
        result = service._extract_html(content)
        assert "<!DOCTYPE html>" in result
        assert "report" in result

    def test_extract_direct_doctype(self):
        """直接以 <!DOCTYPE html> 开头"""
        service = self._get_service()
        content = '<!DOCTYPE html><html><body>direct</body></html>'
        result = service._extract_html(content)
        assert "<!DOCTYPE html>" in result
        assert "direct" in result

    def test_extract_embedded_html(self):
        """HTML 嵌入在文本中间"""
        service = self._get_service()
        content = 'Here is your report:\n<!DOCTYPE html><html><body>embedded</body></html>\nDone.'
        result = service._extract_html(content)
        assert "<!DOCTYPE html>" in result
        assert "embedded" in result

    def test_extract_empty_content(self):
        """空内容返回空字符串"""
        service = self._get_service()
        assert service._extract_html("") == ""
        assert service._extract_html(None) == ""  # type: ignore[arg-type]

    def test_extract_no_html_returns_empty(self):
        """无 HTML 内容返回空字符串"""
        service = self._get_service()
        result = service._extract_html("This is just plain text, no HTML here.")
        assert result == ""

    def test_extract_strips_scripts(self):
        """提取的 HTML 应净化 <script> 标签"""
        service = self._get_service()
        content = '```html\n<!DOCTYPE html><html><body><script>alert(1)</script>safe</body></html>\n```'
        result = service._extract_html(content)
        assert "<script" not in result.lower()
        assert "alert(1)" not in result
        assert "safe" in result

    def test_truncated_html_adds_notice(self):
        """不完整的 HTML（缺少 </html>）应标注截断"""
        service = self._get_service()
        content = '<!DOCTYPE html><html><body><p>incomplete report'
        result = service._extract_html(content)
        assert "截断" in result or "truncat" in result.lower()
        assert result.rstrip().endswith("</html>")

    def test_complete_html_no_truncation_notice(self):
        """完整的 HTML 不应有截断标注"""
        service = self._get_service()
        content = '<!DOCTYPE html><html><body><p>complete</p></body></html>'
        result = service._extract_html(content)
        assert "截断" not in result
        assert "truncat" not in result.lower()


# =========================================================================
# VersionQualityService._wrap_raw_content — XSS 转义
# =========================================================================


class TestWrapRawContent:

    def _get_service(self):
        service = VersionQualityService.__new__(VersionQualityService)
        return service

    def test_escapes_tags_in_title(self):
        """base_tag/head_tag 中的特殊字符应被 HTML 转义"""
        import html as html_module
        service = self._get_service()
        result = service._wrap_raw_content("content", "<script>alert(1)</script>", "v0.2")
        # 标题中不应有未转义的 script 标签
        assert "<script>alert(1)</script>" not in result.split("<title>")[1].split("</title>")[0]
        # 应看到转义后的版本
        assert html_module.escape("<script>alert(1)</script>") in result

    def test_escapes_content(self):
        """content 中的 HTML 应被转义"""
        service = self._get_service()
        result = service._wrap_raw_content("<img onerror=alert(1)>", "v1", "v2")
        assert "<img onerror" not in result.split("<div>")[1]

    def test_empty_content_uses_default(self):
        """空 content 使用默认消息"""
        service = self._get_service()
        result = service._wrap_raw_content("", "v1", "v2")
        assert "报告生成失败" in result


# =========================================================================
# _sanitize_component — 组件名净化
# =========================================================================


class TestSanitizeComponent:

    def test_replaces_unsafe_chars(self):
        """不安全字符替换为下划线"""
        assert _sanitize_component("v0.1.0") == "v0.1.0"
        assert _sanitize_component("a/b/c") == "a_b_c"
        assert _sanitize_component("../etc") == ".._etc"

    def test_empty_returns_unknown(self):
        """空字符串返回 'unknown'"""
        assert _sanitize_component("") == "unknown"

    def test_long_string_truncated(self):
        """超长字符串被截断并附加 hash"""
        long_name = "a" * 100
        result = _sanitize_component(long_name)
        assert len(result) <= 50
        assert result.startswith("a" * 30)
