import json
import logging
import zipfile
import io
from typing import Any

logger = logging.getLogger(__name__)


class TestTimingParser:
    @staticmethod
    def parse(artifact_content: bytes) -> list[dict[str, Any]]:
        try:
            with zipfile.ZipFile(io.BytesIO(artifact_content)) as zf:
                json_files = [f for f in zf.namelist() if f.endswith('.json')]
                if not json_files:
                    logger.warning("No JSON file found in test_timing_data artifact")
                    return []
                with zf.open(json_files[0]) as f:
                    data = json.loads(f.read().decode('utf-8'))
        except zipfile.BadZipFile:
            try:
                data = json.loads(artifact_content.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.error(f"Failed to parse test_timing_data: {e}")
                return []

        results = []
        if isinstance(data, dict):
            if "tests" in data and isinstance(data["tests"], list):
                for entry in data["tests"]:
                    if not isinstance(entry, dict):
                        continue
                    name = entry.get("name", entry.get("test_name", "unknown"))
                    passed = entry.get("passed")
                    if passed is True:
                        result = "passed"
                    elif passed is False:
                        result = "failed"
                    else:
                        result = TestTimingParser._map_result(entry)
                    duration = TestTimingParser._extract_duration(entry)
                    if duration is None and "elapsed" in entry:
                        try:
                            duration = float(entry["elapsed"])
                        except (ValueError, TypeError):
                            pass
                    results.append({
                        "test_name": name,
                        "test_file": name,
                        "result": result,
                        "duration_seconds": duration,
                        "data_granularity": "file_level",
                    })
            else:
                for test_file, info in data.items():
                    result = TestTimingParser._map_result(info)
                    duration = TestTimingParser._extract_duration(info)
                    results.append({
                        "test_name": test_file,
                        "test_file": test_file,
                        "result": result,
                        "duration_seconds": duration,
                        "data_granularity": "file_level",
                    })
        elif isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict):
                    name = entry.get("name", entry.get("test_name", "unknown"))
                    result = TestTimingParser._map_result(entry)
                    duration = TestTimingParser._extract_duration(entry)
                    results.append({
                        "test_name": name,
                        "test_file": entry.get("file", name),
                        "result": result,
                        "duration_seconds": duration,
                        "data_granularity": "file_level",
                    })
        return results

    @staticmethod
    def _map_result(info: dict | Any) -> str:
        if not isinstance(info, dict):
            return "unknown"
        if "passed" in info:
            return "passed" if info["passed"] is True else "failed" if info["passed"] is False else "unknown"
        status = info.get("status", info.get("result", ""))
        if isinstance(status, bool):
            return "passed" if status else "failed"
        if isinstance(status, str):
            mapping = {
                "success": "passed", "passed": "passed", "PASS": "passed",
                "fail": "failed", "failed": "failed", "FAIL": "failed", "error": "failed",
                "skip": "skipped", "skipped": "skipped", "SKIP": "skipped",
            }
            return mapping.get(status.lower(), status.lower())
        return "unknown"

    @staticmethod
    def _extract_duration(info: dict | Any) -> float | None:
        if not isinstance(info, dict):
            return None
        for key in ("duration", "duration_seconds", "time", "elapsed", "runtime"):
            val = info.get(key)
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    continue
        return None
