"""Parse the actual vLLM/vLLM-Ascend checkout printed by CI logs."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

PARSER_VERSION = 1
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_FIELD = re.compile(r"^\s*(Branch|Commit hash|Date|Message|Tags|Remote)\s*:\s*(.*?)\s*$", re.I)


def _iso_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S %z").isoformat()
    except ValueError:
        return value.strip()


def parse_ci_version_snapshot(log_text: str, *, source_job_id: int | None = None) -> dict[str, Any] | None:
    if isinstance(log_text, bytes):
        log_text = log_text.decode("utf-8", errors="replace")
    text = _ANSI.sub("", log_text or "")
    lines = [
        re.sub(r"^\d{4}-\d{2}-\d{2}T\S+Z\s+", "", line).replace("##[group]", "")
        for line in text.splitlines()
    ]
    blocks: dict[str, dict[str, str]] = {}
    current: str | None = None
    for line in lines:
        normalized = line.strip()
        if re.search(r"vLLM-Ascend\s+Git information", normalized, re.I):
            current = "vllm_ascend"
            blocks[current] = {}
            continue
        if re.search(r"vLLM\s+Git information", normalized, re.I):
            current = "vllm"
            blocks[current] = {}
            continue
        match = _FIELD.match(normalized)
        if current and match:
            blocks[current][match.group(1).lower().replace(" ", "_")] = match.group(2)

    package_versions: dict[str, str] = {}
    for line in lines:
        match = re.match(r"^\s*(vllm(?:[_-]ascend)?)\s+([0-9][^\s]*)", line, re.I)
        if match:
            package_versions[match.group(1).lower().replace("-", "_")] = match.group(2)

    if not blocks and not package_versions:
        return None
    result: dict[str, Any] = {
        "parser_version": PARSER_VERSION,
        "source_job_id": source_job_id,
        "source_step": "Stream logs",
        "status": "complete" if blocks.get("vllm_ascend", {}).get("commit_hash") else "partial",
    }
    for prefix in ("vllm", "vllm_ascend"):
        block = blocks.get(prefix, {})
        result[f"{prefix}_version"] = package_versions.get(prefix)
        result[f"{prefix}_commit"] = block.get("commit_hash")
        result[f"{prefix}_commit_date"] = _iso_date(block.get("date"))
        result[f"{prefix}_commit_message"] = block.get("message")
        result[f"{prefix}_branch"] = block.get("branch")
    return result


def get_version_snapshot(run_data: Any) -> dict[str, Any]:
    if isinstance(run_data, str):
        import json
        try:
            run_data = json.loads(run_data)
        except (TypeError, ValueError):
            return {}
    if not isinstance(run_data, dict):
        return {}
    evidence = run_data.get("dashboard_evidence") or {}
    snapshot = evidence.get("version_snapshot") or {}
    return snapshot if isinstance(snapshot, dict) else {}
