from types import SimpleNamespace
from unittest.mock import AsyncMock
from zipfile import ZipFile

import pytest

from failure_analysis.failure_analysis import FailureAnalysisService


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
