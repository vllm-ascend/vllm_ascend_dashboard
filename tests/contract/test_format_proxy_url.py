"""回归测试：FormatProxy 上游 chat/completions URL 构造。

复现并防止 format_proxy.py 中 urljoin(base+"/", "v1/chat/completions")
在 base_url 已含 /v1（如 DashScope compatible-mode）时产生双重 /v1/v1/ 路径
导致上游 400 "Invalid model name" 的问题。
"""
from tooling.parsers.format_proxy import FormatProxy


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


def test_reasoning_content_fallback_for_non_stream_response():
    """Reasoning-only upstream responses must remain visible to Claude CLI."""
    p = _make("https://gateway.example/v1")
    response = p._openai_resp_to_anthropic(
        {
            "id": "chatcmpl-test",
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": '{"problem_category":"其他"}',
                },
                "finish_reason": "stop",
            }],
        },
        {"messages": []},
    )
    assert response["content"] == [{
        "type": "text",
        "text": '{"problem_category":"其他"}',
    }]


def test_content_blocks_are_normalized():
    """OpenAI-compatible block arrays should be converted to text."""
    p = _make("https://gateway.example/v1")
    response = p._openai_resp_to_anthropic(
        {
            "choices": [{
                "message": {
                    "content": [{"type": "text", "text": "part-1"}, "part-2"],
                },
                "finish_reason": "stop",
            }],
        },
        {"messages": []},
    )
    assert response["content"] == [{"type": "text", "text": "part-1part-2"}]


def test_stream_reasoning_content_is_forwarded_and_length_preserved():
    """Streaming reasoning and truncation metadata must not be discarded."""
    p = _make("https://gateway.example/v1")
    state = {
        "msg_id": "msg-test",
        "model": "m",
        "content_index": 0,
        "tool_use_index": 0,
        "started": False,
        "finished": False,
        "input_tokens": 0,
        "output_tokens": 0,
        "current_tool_call": None,
        "pending_tool_calls": {},
        "sent_text_block_start": False,
        "sent_tool_blocks": set(),
    }
    events = p._openai_chunk_to_anthropic_events(
        {
            "choices": [{
                "delta": {"content": "", "reasoning_content": "reasoning"},
                "finish_reason": "length",
            }],
        },
        state,
    )
    assert any('"text": "reasoning"' in event for event in events)
    assert any('"stop_reason": "max_tokens"' in event for event in events)


def test_cli_json_envelope_reasoning_content_fallback():
    """Nested CLI envelopes should expose reasoning-only output to the parser."""
    from infrastructure.clients.claude_code_cli import ClaudeCodeCLI

    payload = {
        "result": {
            "content": "",
            "reasoning_content": '{"problem_category":"其他"}',
        }
    }
    assert ClaudeCodeCLI._content_from_payload(payload) == (
        '{"problem_category":"其他"}'
    )


def test_detect_api_error_signatures():
    """failure_analysis 的 API 错误检测应识别上游错误，避免误标 completed。"""
    from failure_analysis.failure_analysis import FailureAnalysisService

    detect = FailureAnalysisService._detect_api_error
    # 真实复现的上游错误
    assert detect("API Error: 400 /chat/completions: Invalid model name passed in model=glm-5.1")  # type: ignore[arg-type]
    assert detect("invalid model name: glm-5.1 not found")  # type: ignore[arg-type]
    # 正常分析内容（长且含 error 字样）不应被误判
    long_analysis = "根因分析：该 CI 失败由 error in pytest 引起，" + "x" * 500
    assert detect(long_analysis) is None  # type: ignore[arg-type]
    assert detect("") is None  # type: ignore[arg-type]
