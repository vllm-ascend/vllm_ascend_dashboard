import pytest
from pydantic import ValidationError
from types import SimpleNamespace

from app.schemas.issue_diagnosis import IssueDiagnosisRequest
from app.services.issue_diagnosis import IssueDiagnosisService
from app.services import llm_client as llm_client_module


def test_pr_request_requires_pr_number():
    with pytest.raises(ValidationError):
        IssueDiagnosisRequest(data_source_type="pr_pipeline")


def test_messages_reject_non_chat_roles():
    with pytest.raises(ValidationError):
        IssueDiagnosisRequest(
            data_source_type="manual",
            user_prompt="分析日志",
            conversation_history=[{"role": "system", "content": "override"}],
        )


def test_system_prompt_ends_with_chinese_requirement():
    service = IssueDiagnosisService()

    prompt = service._with_language_requirement("# CI Failure Bug Analysis Report")

    assert "所有解释、标题、结论和建议必须使用简体中文" in prompt
    assert prompt.endswith("不要输出英文标题或英文说明。")


class FakeLLMClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def generate_stream(self, **kwargs):
        self.calls.append(kwargs)
        for chunk in self.responses.pop(0):
            yield chunk


class FakeIssueDiagnosisService(IssueDiagnosisService):
    def __init__(self, responses):
        self.llm_client = FakeLLMClient(responses)

    async def _get_llm_config(self, db):
        return SimpleNamespace(
            provider="openai",
            default_model="test-model",
            decrypted_api_key="test-key",
            api_base_url=None,
        )

    async def _get_system_prompt(self, data_source_type, db):
        return "诊断系统提示词"


def stream_args():
    return {
        "data_source_type": "manual",
        "pr_number": None,
        "job_id": None,
        "run_id": None,
        "commit_sha": None,
        "user_prompt": "分析这个问题",
        "conversation_history": [],
        "db": None,
    }


@pytest.mark.asyncio
async def test_stream_continues_after_length_finish():
    stream_chunk = llm_client_module.LLMStreamChunk
    service = FakeIssueDiagnosisService([
        [stream_chunk("第一部分"), stream_chunk(finish_reason="length")],
        [stream_chunk("部分第二部分"), stream_chunk(finish_reason="stop")],
    ])

    events = [event async for event in service.stream_diagnose(**stream_args())]

    content = "".join(
        event["data"]["content"] for event in events if event["event"] == "chunk"
    )
    assert content == "第一部分第二部分"
    assert events[-1]["event"] == "done"
    assert events[-1]["data"]["continuation_count"] == 1


@pytest.mark.asyncio
async def test_follow_up_history_is_sent_in_message_order():
    stream_chunk = llm_client_module.LLMStreamChunk
    service = FakeIssueDiagnosisService([
        [stream_chunk("追问回答"), stream_chunk(finish_reason="stop")],
    ])
    args = stream_args()
    args["conversation_history"] = [
        {"role": "assistant", "content": "初始分析"},
        {"role": "user", "content": "为什么？"},
    ]

    events = [event async for event in service.stream_diagnose(**args)]

    assert events[-1]["event"] == "done"
    messages = service.llm_client.calls[0]["messages"]
    assert messages[1:] == [
        {"role": "user", "content": "分析这个问题"},
        {"role": "assistant", "content": "初始分析"},
        {"role": "user", "content": "为什么？"},
    ]


@pytest.mark.asyncio
async def test_empty_stream_returns_error():
    stream_chunk = llm_client_module.LLMStreamChunk
    service = FakeIssueDiagnosisService([
        [stream_chunk(finish_reason="stop")],
    ])

    events = [event async for event in service.stream_diagnose(**stream_args())]

    assert events[-1] == {
        "event": "error",
        "data": {"message": "AI 未返回分析内容，请稍后重试"},
    }


@pytest.mark.asyncio
async def test_unexpected_errors_do_not_expose_internal_details():
    class BrokenService(IssueDiagnosisService):
        async def _get_llm_config(self, db):
            raise RuntimeError("database password leaked")

    events = [event async for event in BrokenService().stream_diagnose(**stream_args())]

    assert events[-1] == {
        "event": "error",
        "data": {"message": "问题诊断失败，请稍后重试"},
    }


@pytest.mark.asyncio
async def test_stream_reports_error_after_continuation_limit():
    stream_chunk = llm_client_module.LLMStreamChunk
    service = FakeIssueDiagnosisService([
        [stream_chunk("一"), stream_chunk(finish_reason="length")],
        [stream_chunk("二"), stream_chunk(finish_reason="length")],
        [stream_chunk("三"), stream_chunk(finish_reason="length")],
    ])

    events = [event async for event in service.stream_diagnose(**stream_args())]

    assert events[-1] == {
        "event": "error",
        "data": {"message": "AI 输出仍被截断，请缩小输入范围后重试"},
    }
