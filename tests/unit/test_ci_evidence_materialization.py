import hashlib
import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from collector.ci import CICollector
from infrastructure.core.config import settings


def _zip_payload() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("logs/result.txt", "failure details")
    return output.getvalue()


@pytest.mark.asyncio
async def test_on_demand_artifacts_are_run_scoped_and_incremental(tmp_path) -> None:
    payload = _zip_payload()
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()

    class GitHub:
        downloads = 0

        async def list_artifacts(self, run_id):
            assert run_id == 42
            return [{"id": 7, "name": "model / logs", "digest": digest}]

        async def download_artifact(self, artifact_id):
            assert artifact_id == 7
            self.downloads += 1
            return payload

    old_data_dir = settings.DATA_DIR
    settings.DATA_DIR = str(tmp_path)
    try:
        collector = CICollector(GitHub(), SimpleNamespace())
        await collector.materialize_run_artifacts(42)
        await collector.materialize_run_artifacts(42)
    finally:
        settings.DATA_DIR = old_data_dir

    run_dir = tmp_path / "ci-evidence" / "runs" / "42"
    archive = run_dir / "artifacts" / "7_model_logs.zip"
    assert archive.is_file()
    assert (run_dir / "extracted" / "7_model_logs" / "logs" / "result.txt").read_text() == "failure details"
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["artifacts"]["7"]["state"] == "ready"
    assert collector.github.downloads == 1, "complete evidence must not be re-downloaded"
