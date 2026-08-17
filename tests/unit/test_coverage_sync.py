import os
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from coverage import CoverageData

from test_board import coverage_sync


def _write_covdata(path: Path, source_path: str, lines: set[int]) -> None:
    data = CoverageData(basename=str(path), suffix=False)
    data.add_lines({source_path: lines})
    data.write()


def _make_tar(tmp_path: Path) -> Path:
    tar_path = tmp_path / "coverage.tar"
    members = [
        (
            "VLLM-ASCEND@task-a/tests__ut__sample--test_a/covdata/"
            "coverage.linux-aarch64-a3-1-runner",
            {1, 2},
        ),
        (
            "VLLM-ASCEND@task-b/tests__ut__sample--test_b/covdata/"
            "coverage.linux-aarch64-a2-1-runner",
            {2, 3},
        ),
        (
            "VLLM-ASCEND@task-c/tests__e2e__sample--test_c/covdata/"
            "coverage.linux-aarch64-a3-1-runner",
            {4},
        ),
    ]
    source_path = "/__w/vllm-ascend/vllm-ascend/vllm_ascend/sample.py"
    with tarfile.open(tar_path, "w") as archive:
        for index, (member_name, lines) in enumerate(members):
            data_path = tmp_path / f"coverage-{index}.data"
            _write_covdata(data_path, source_path, lines)
            archive.add(data_path, arcname=member_name)
    return tar_path


def test_read_covdata_uses_coverage_public_api(tmp_path: Path) -> None:
    data_path = tmp_path / ".coverage"
    source_path = "/__w/vllm-ascend/vllm-ascend/vllm_ascend/sample.py"
    _write_covdata(data_path, source_path, {1, 3})

    result = coverage_sync.read_covdata(data_path)

    assert result is not None
    assert result["files"] == ["vllm_ascend/sample.py"]
    assert result["lines"]["vllm_ascend/sample.py"] == [1, 3]


def test_breadth_preserves_job_to_file_matrix(tmp_path: Path) -> None:
    result = coverage_sync._process_tar_breadth(_make_tar(tmp_path), "test-signature")

    assert result["summary"]["total_jobs"] == 3
    assert result["summary"]["by_test_type"] == {"ut": 2, "e2e": 1}
    assert result["summary"]["by_hardware"] == {"A3": 2, "A2": 1}
    assert result["file_matrix"] == [
        {
            "source_path": "vllm_ascend/sample.py",
            "module": "vllm_ascend",
            "covered_by_jobs": 3,
            "covered_by_hardware": ["A2", "A3"],
        }
    ]


def test_line_coverage_filters_to_ut_and_calculates_source_denominator(
    tmp_path: Path, monkeypatch
) -> None:
    source_dir = tmp_path / "vllm_ascend"
    source_dir.mkdir()
    (source_dir / "sample.py").write_text(
        "def sample(value):\n"
        "    if value:\n"
        "        return 1\n"
        "    return 2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        coverage_sync,
        "get_github_cache",
        lambda: SimpleNamespace(
            cache_dir=tmp_path,
            get_latest_commit=lambda: {"sha": "test-commit"},
        ),
    )

    result = coverage_sync._process_line_coverage(_make_tar(tmp_path), "test-signature")

    assert result["test_type"] == "ut"
    assert result["status"] == "ok"
    assert result["source_commit"] == "test-commit"
    assert result["totals"]["num_statements"] > result["totals"]["covered_lines"]
    assert result["totals"]["missing_lines"] > 0
    assert result["files"][0]["path"] == "vllm_ascend/sample.py"
    assert result["details"]["vllm_ascend/sample.py"]["executed_lines"] == [1, 2, 3]


@pytest.mark.asyncio
async def test_download_failure_removes_partial_temp_tar(tmp_path: Path, monkeypatch) -> None:
    temp_path = tmp_path / "coverage-download.tar"
    fd = os.open(temp_path, os.O_CREAT | os.O_RDWR)
    monkeypatch.setattr(
        coverage_sync.tempfile,
        "mkstemp",
        lambda **_: (fd, str(temp_path)),
    )

    async def fail_signature(_client):
        raise RuntimeError("signature request failed")

    monkeypatch.setattr(coverage_sync, "_head_signature", fail_signature)

    with pytest.raises(RuntimeError, match="signature request failed"):
        await coverage_sync._download_with_signature()

    assert not temp_path.exists()
