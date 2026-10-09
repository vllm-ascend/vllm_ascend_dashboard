from datetime import UTC, datetime

from collector.npu_job_facts import build_fact_values


def test_fact_uses_github_job_created_at_as_queue_start() -> None:
    values = build_fact_values(
        {
            "id": 101,
            "name": "e2e-a3",
            "status": "queued",
            "created_at": "2026-10-09T06:00:00Z",
            "started_at": "2026-10-09T06:00:00Z",
            "labels": ["unknown-runner"],
        },
        {"id": 22, "html_url": "https://example.test/run/22"},
        repository="example/repo",
        workflow_name="NPU E2E",
    )

    assert values["queued_at"] == datetime(2026, 10, 9, 6, 0, tzinfo=UTC)
    assert values["queued_at_source"] == "github_job_created_at"
    assert values["started_at"] == values["queued_at"]
    assert values["mapping_status"] == "unmatched"


def test_fact_marks_missing_github_queue_timestamp_not_zero() -> None:
    values = build_fact_values(
        {"id": 102, "status": "queued", "labels": []},
        {"id": 23},
        repository="example/repo",
        workflow_name="NPU E2E",
    )

    assert values["queued_at"] is None
    assert values["queued_at_source"] == "missing"
    assert values["data_quality_status"] == "missing_queued_at"


def test_fact_maps_a5_runner_using_config_json_rule() -> None:
    values = build_fact_values(
        {"id": 103, "status": "completed", "labels": ["linux-aarch64-a5-8"]},
        {"id": 24},
        repository="vllm-project/vllm-ascend",
        workflow_name="PR E2E",
    )

    assert values["mapping_status"] == "matched"
    assert values["pool"] == "A5 池"
    assert values["accelerator_model"] == "A5"
    assert values["mapped_cards"] == 8
