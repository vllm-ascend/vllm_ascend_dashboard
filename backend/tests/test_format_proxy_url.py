"""回归测试：FormatProxy 上游 chat/completions URL 构造。

复现并防止 format_proxy.py 中 urljoin(base+"/", "v1/chat/completions")
在 base_url 已含 /v1（如 DashScope compatible-mode）时产生双重 /v1/v1/ 路径
导致上游 400 "Invalid model name" 的问题。
"""
from app.services.format_proxy import FormatProxy


def _make(base: str) -> FormatProxy:
    return FormatProxy(upstream_base_url=base, upstream_api_key="k", upstream_model="m")


def test_base_with_v1_dashscope():
    """DashScope compatible-mode 地址已含 /v1，不应再追加 /v1。"""
    p = _make("https://dashscope.aliyuncs.com/compatible-mode/v1")
    assert p._chat_completions_url() == (
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    )


def test_base_with_v1_trailing_slash():
    """带尾斜杠的 /v1 地址需先 strip 再判断。"""
    p = _make("https://dashscope.aliyuncs.com/compatible-mode/v1/")
    assert p._chat_completions_url() == (
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    )


def test_base_without_v1_openai():
    """不含 /v1 的 base（如官方 OpenAI）应追加 /v1/chat/completions。"""
    p = _make("https://api.openai.com")
    assert p._chat_completions_url() == "https://api.openai.com/v1/chat/completions"


def test_base_without_v1_trailing_slash():
    p = _make("https://api.openai.com/")
    assert p._chat_completions_url() == "https://api.openai.com/v1/chat/completions"


def test_base_exactly_v1():
    """base 恰好以 /v1 结尾（无前缀路径）。"""
    p = _make("https://example.com/v1")
    assert p._chat_completions_url() == "https://example.com/v1/chat/completions"


def test_no_double_v1():
    """核心回归断言：绝不能出现 /v1/v1/ 双重路径。"""
    p = _make("https://dashscope.aliyuncs.com/compatible-mode/v1")
    url = p._chat_completions_url()
    assert "/v1/v1/" not in url


def test_detect_api_error_signatures():
    """failure_analysis 的 API 错误检测应识别上游错误，避免误标 completed。"""
    from app.services.failure_analysis import FailureAnalysisService

    detect = FailureAnalysisService._detect_api_error
    # 真实复现的上游错误
    assert detect("API Error: 400 /chat/completions: Invalid model name passed in model=glm-5.1")  # type: ignore[arg-type]
    assert detect("invalid model name: glm-5.1 not found")  # type: ignore[arg-type]
    # 正常分析内容（长且含 error 字样）不应被误判
    long_analysis = "根因分析：该 CI 失败由 error in pytest 引起，" + "x" * 500
    assert detect(long_analysis) is None  # type: ignore[arg-type]
    assert detect("") is None  # type: ignore[arg-type]
