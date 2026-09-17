from tooling.ci_version_snapshot import get_version_snapshot, parse_ci_version_snapshot


def test_parse_stream_logs_git_blocks_and_package_versions():
    logs = """
Installed vLLM-related Python packages:
vllm 0.28.0+empty /vllm-workspace/vllm
vllm_ascend 0.19.1rc2.dev2124+g90b5dd80d /vllm-workspace/vllm-ascend
vLLM Git information
Branch: HEAD
Commit hash: 2cf0a6915ce544dc493a0990f2ea38d81601128a
Date: 2026-08-23 01:09:27 -0700
Message: Pin Cython (#53358)
vLLM-Ascend Git information
Branch: HEAD
Commit hash: 90b5dd80d0180c4ddfe6d46a252d93d632b3c16b
Date: 2026-09-14 21:26:49 +0800
Message: Fallback to gate forward (#16521)
"""
    snapshot = parse_ci_version_snapshot(logs, source_job_id=123)
    assert snapshot is not None
    assert snapshot["status"] == "complete"
    assert snapshot["source_step"] == "Stream logs"
    assert snapshot["vllm_version"] == "0.28.0+empty"
    assert snapshot["vllm_ascend_commit"] == "90b5dd80d0180c4ddfe6d46a252d93d632b3c16b"
    assert snapshot["vllm_ascend_commit_date"] == "2026-09-14T21:26:49+08:00"


def test_snapshot_does_not_fall_back_to_workflow_head_sha():
    assert get_version_snapshot({"head_sha": "workflow-sha"}) == {}
    partial = parse_ci_version_snapshot("vllm_ascend 0.19.0 /workspace")
    assert partial is not None
    assert partial["vllm_ascend_commit"] is None
    assert partial["status"] == "partial"
