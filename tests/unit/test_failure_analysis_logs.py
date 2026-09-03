import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zipfile import ZipFile

import pytest

from failure_analysis.failure_analysis import FailureAnalysisService
from infrastructure.clients.claude_code_cli import ClaudeCodeCLI


def test_extract_report_summary_unwraps_nested_json_envelope():
    payload = (
        '{"result":"{\\"report\\":{\\"problem_category\\":\\"基础设施\\",'
        '\\"root_cause_summary\\":\\"Runner 断开\\",'
        '\\"improvement_measures_summary\\":\\"重试并检查 Runner\\"}}"}'
    )

    assert FailureAnalysisService._extract_report_summary(payload) == {
        "problem_category": "基础设施",
        "root_cause_summary": "Runner 断开",
        "improvement_measures_summary": "重试并检查 Runner",
    }


def test_extract_report_summary_reads_fields_from_malformed_wrapper():
    payload = (
        '前置说明 {"problem_category":"其他", '
        '"root_cause_summary":"证据不足", '
        '"improvement_measures_summary":"补充日志"'
    )

    assert FailureAnalysisService._extract_report_summary(payload) == {
        "problem_category": "其他",
        "root_cause_summary": "证据不足",
        "improvement_measures_summary": "补充日志",
    }


def test_extract_report_summary_accepts_gateway_aliases_and_list_values():
    payload = (
        '{"report":{"category":"基础设施", "root_cause":"Runner 断开", '
        '"recommendations":["重试任务", "检查 Runner"]}}'
    )

    assert FailureAnalysisService._extract_report_summary(payload) == {
        "problem_category": "基础设施",
        "root_cause_summary": "Runner 断开",
        "improvement_measures_summary": "重试任务；检查 Runner",
    }


def test_extract_report_summary_merges_sibling_json_objects():
    payload = (
        '{"result":{"problem_category":"基础设施"},'
        '"content":{"root_cause_summary":"Runner 断开",'
        '"improvement_measures_summary":"重试并检查 Runner"}}'
    )

    assert FailureAnalysisService._extract_report_summary(payload) == {
        "problem_category": "基础设施",
        "root_cause_summary": "Runner 断开",
        "improvement_measures_summary": "重试并检查 Runner",
    }


def test_extract_report_summary_recovers_markdown_headings_without_json_footer():
    payload = """## 失败原因
Runner 在初始化阶段断开，日志显示连接被远端关闭。

## 改进建议
检查 Runner 网络和启动依赖后重新执行。
"""

    assert FailureAnalysisService._extract_report_summary(payload) == {
        "root_cause_summary": "Runner 在初始化阶段断开，日志显示连接被远端关闭。",
        "improvement_measures_summary": "检查 Runner 网络和启动依赖后重新执行。",
    }


def test_cli_prefers_nested_answer_with_more_report_fields():
    payload = {
        "result": '{"problem_category":"基础设施"}',
        "content": '{"problem_category":"基础设施",'
        '"root_cause_summary":"Runner 断开",'
        '"improvement_measures_summary":"重试并检查 Runner"}',
    }

    assert ClaudeCodeCLI._content_from_payload(payload) == payload["content"]


def test_cli_max_turns_envelope_is_not_treated_as_partial_report():
    payload = {
        "type": "result",
        "subtype": "error_max_turns",
        "is_error": True,
        "terminal_reason": "max_turns",
        "num_turns": 101,
    }
    cli = ClaudeCodeCLI()

    result = cli._parse_output(
        json.dumps(payload), "", 1.0, "json", "glm-5.3", exit_code=1
    )

    assert result.turns == 101
    assert ClaudeCodeCLI._error_from_payload(result.raw_json) == (
        "Claude Code CLI 在生成最终报告前达到最大分析轮次"
        "（已执行 101 轮）；请缩小分析范围或提高轮次上限后重试"
    )


def test_legacy_parser_recovery_is_usable_for_missing_renderer_fields():
    parsed = FailureAnalysisService.parse_llm_response(
        '{"root_cause_summary":"Runner 断开",'
        '"improvement_measures_summary":"重试并检查 Runner"}'
    )

    assert parsed["root_cause_summary"] == "Runner 断开"
    assert parsed["improvement_measures_summary"] == "重试并检查 Runner"
    assert FailureAnalysisService._has_recoverable_report_text(parsed) is True


def test_extract_job_log_from_run_zip_uses_matching_matrix_job(tmp_path):
    archive_path = tmp_path / "run-logs.zip"
    destination = tmp_path / "logs" / "123.log"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "single-node (main, qwen3)/0_Setup.txt",
            "target failure output",
        )
        archive.writestr(
            "single-node (main, glm)/0_Setup.txt",
            "different matrix job",
        )

    recovered = FailureAnalysisService._extract_job_log_from_run_zip(
        archive_path,
        job_id=123,
        job_name="single-node (main, qwen3)",
        destination=destination,
    )

    assert recovered is True
    assert "target failure output" in destination.read_text(encoding="utf-8")
    assert "different matrix job" not in destination.read_text(encoding="utf-8")


def test_extract_job_log_from_run_zip_rejects_ambiguous_job(tmp_path):
    archive_path = tmp_path / "run-logs.zip"
    destination = tmp_path / "logs" / "123.log"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("unrelated-job/0_Setup.txt", "unrelated")

    recovered = FailureAnalysisService._extract_job_log_from_run_zip(
        archive_path,
        job_id=123,
        job_name="single-node (main, qwen3)",
        destination=destination,
    )

    assert recovered is False
    assert not destination.exists()


@pytest.mark.asyncio
async def test_log_preparation_failure_marks_existing_analysis_failed():
    job = SimpleNamespace(
        job_id=123,
        run_id=456,
        workflow_name="Nightly-A3",
        job_name="single-node (main, qwen3)",
        conclusion="failure",
        completed_at=None,
        steps_data="[]",
    )
    analysis = SimpleNamespace(
        id=99,
        analysis_status="analyzing",
        analysis_phase="queued",
        error_message=None,
        failure_fingerprint=None,
        triggered_by="manual",
    )

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    db = AsyncMock()
    db.execute.side_effect = [Result(job), Result(analysis)]
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.commit = AsyncMock()

    service = FailureAnalysisService()
    service._get_llm_config = AsyncMock(
        return_value=SimpleNamespace(
            provider="zhipu",
            decrypted_api_key="masked",
            api_base_url="https://example.test",
            default_model="glm-5.2",
        )
    )
    service._get_agent_config = AsyncMock(
        return_value={"runtime": "claude_cli", "max_turns": 3, "timeout_seconds": 60}
    )
    service._get_system_prompt = AsyncMock(return_value="prompt")
    service._build_job_context = AsyncMock(
        side_effect=RuntimeError("Required GitHub job log unavailable")
    )

    result = await service.analyze_failed_job(123, db, force=True)

    assert result is analysis
    assert analysis.analysis_status == "failed"
    assert analysis.analysis_phase == "failed"
    assert "Required GitHub job log unavailable" in analysis.error_message
    db.commit.assert_awaited_once()
