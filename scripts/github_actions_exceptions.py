#!/usr/bin/env python3
"""Print the daily workflow summary and exceptional GitHub Actions jobs.

Usage:
    python scripts/github_actions_exceptions.py <run-url>

Optional authentication:
    PowerShell: $env:GITHUB_TOKEN = "github_pat_..."

The report includes failed, queued, cancelled, and skipped jobs. The two
housekeeping jobs ``clear-pre-logs`` and
``single-node-accuracy-tests-pr-only`` are excluded.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
FO_MAP_PATH = REPO_ROOT / "data" / "model_fo_map.json"
EXCLUDED_JOB_NAMES = {"clear-pre-logs", "single-node-accuracy-tests-pr-only"}


def parse_run_url(run_url: str) -> tuple[str, str, str]:
    match = re.fullmatch(
        r"https?://github\.com/([^/]+/[^/]+)/actions/runs/(\d+)/?",
        run_url.strip(),
    )
    if not match:
        raise ValueError(
            "链接必须是 https://github.com/<owner>/<repo>/actions/runs/<run_id>"
        )
    owner_repo, run_id = match.groups()
    return owner_repo, run_id, run_url.rstrip("/")


def github_headers() -> dict[str, str]:
    token = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "vllm-ascend-dashboard-actions-report",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def github_get(url: str) -> dict | list:
    request = Request(url, headers=github_headers())
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code == 403:
            raise RuntimeError(
                "GitHub API 请求受限，请稍后重试或配置 GITHUB_TOKEN 环境变量"
            ) from exc
        raise RuntimeError(f"GitHub API 请求失败：HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"无法访问 GitHub API：{exc.reason}") from exc


def github_get_bytes(url: str) -> bytes:
    request = Request(url, headers=github_headers())
    try:
        with urlopen(request, timeout=60) as response:
            return response.read()
    except HTTPError as exc:
        raise RuntimeError(f"GitHub 日志请求失败：HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"无法访问 GitHub 日志：{exc.reason}") from exc


def fetch_run(owner_repo: str, run_id: str) -> dict:
    payload = github_get(f"https://api.github.com/repos/{owner_repo}/actions/runs/{run_id}")
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub Actions run 返回格式无效")
    return payload


def fetch_job_logs(owner_repo: str, job_id: int) -> str:
    payload = github_get_bytes(
        f"https://api.github.com/repos/{owner_repo}/actions/jobs/{job_id}/logs"
    )
    archive = io.BytesIO(payload)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zipped:
            return "\n".join(
                zipped.read(name).decode("utf-8", errors="replace")
                for name in zipped.namelist()
            )
    return payload.decode("utf-8", errors="replace")


def extract_version_info(log_text: str) -> dict[str, str]:
    """Extract vLLM/CANN information from the standard nightly log steps."""
    unknown = "\u672a\u83b7\u53d6"
    versions = {"vllm": unknown, "vllm_commit": unknown, "cann": unknown}
    version_pattern = r"v?(\d+\.\d+(?:\.\d+){0,2}(?:[-+._A-Za-z0-9]*)?)"
    section = ""
    cann_context = False

    def normalize_vllm(value: str) -> str:
        return value if value.lower().startswith("v") else f"v{value}"

    def normalize_cann(value: str) -> str:
        return value.lstrip("vV")

    for line in log_text.splitlines():
        lower = line.lower().strip()

        if "vllm-ascend git information" in lower:
            section = "vllm-ascend"
        elif "vllm git information" in lower and "ascend" not in lower:
            section = "vllm"
        elif "installed vllm-related python packages" in lower:
            section = "packages"

        sha_match = re.search(r"\b[0-9a-f]{40}\b", line, re.IGNORECASE)
        if sha_match and section == "vllm" and "commit" in lower:
            versions["vllm_commit"] = sha_match.group(0)
        elif sha_match and "vllm" in lower and "ascend" not in lower:
            if "commit" in lower or "sha" in lower:
                versions["vllm_commit"] = sha_match.group(0)

        package_match = re.search(
            rf"\bvllm(?!-ascend)(?:\s+|==?|:)\s*({version_pattern})",
            line,
            re.IGNORECASE,
        )
        if package_match and versions["vllm"] == unknown:
            versions["vllm"] = normalize_vllm(package_match.group(1))

        if "vllm.__version__" in lower or "vllm version" in lower:
            match = re.search(version_pattern, line, re.IGNORECASE)
            if match and versions["vllm"] == unknown:
                versions["vllm"] = normalize_vllm(match.group(1))

        if "cann" in lower or "ascend_toolkit_install.info" in lower:
            cann_context = True

        cann_match = re.search(
            rf"\bcann(?:[_ -]?version)?\s*[:=]\s*({version_pattern})",
            line,
            re.IGNORECASE,
        )
        if cann_match is None:
            cann_match = re.search(
                rf"\bcann[:/]({version_pattern})",
                line,
                re.IGNORECASE,
            )
        if cann_match is None and cann_context and "version" in lower:
            cann_match = re.search(
                rf"\bversion\s*[:=]\s*({version_pattern})",
                line,
                re.IGNORECASE,
            )
        if cann_match and versions["cann"] == unknown:
            versions["cann"] = normalize_cann(cann_match.group(1))

    return versions


def build_run_summary(run: dict, jobs: list[dict], owner_repo: str) -> str:
    unknown = "\u672a\u83b7\u53d6"
    created_at = run.get("created_at") or run.get("run_started_at")
    if created_at:
        timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        local_time = timestamp.astimezone(ZoneInfo("Asia/Shanghai"))
        date_label = f"{local_time.month}/{local_time.day}"
    else:
        date_label = unknown

    branch = str(run.get("head_branch") or unknown)
    branch_label = branch.replace("/", "-")
    head_sha = str(run.get("head_sha") or unknown)
    info = {"vllm": unknown, "vllm_commit": unknown, "cann": unknown}

    candidates = [
        job
        for job in jobs
        if any(
            "vllm" in str(step.get("name", "")).lower()
            or "cann" in str(step.get("name", "")).lower()
            for step in (job.get("steps") or [])
        )
    ]
    for job in candidates[:10]:
        try:
            extracted = extract_version_info(fetch_job_logs(owner_repo, int(job["id"])))
        except (HTTPError, RuntimeError, OSError, ValueError, zipfile.BadZipFile):
            continue
        for key, value in extracted.items():
            if value != unknown:
                info[key] = value
        if all(value != unknown for value in info.values()):
            break

    run_link = str(
        run.get("html_url")
        or f"https://github.com/{owner_repo}/actions/runs/{run.get('id', '')}"
    )
    return (
        f"【{date_label} vllm_ascend 社区 {branch_label}分支 nightly 冒烟】\n"
        f"vllm-ascend: {branch_label} 【{head_sha}】\n"
        f"vllm: {info['vllm']}【{info['vllm_commit']}】\n"
        f"cann: {info['cann']}\n"
        f"{run_link}"
    )


def load_fo_map() -> dict[str, str]:
    with FO_MAP_PATH.open(encoding="utf-8") as file:
        data = json.load(file)
    return {str(key): str(value) for key, value in data.items() if not key.startswith("_")}


def config_name(job_name: str) -> str:
    """Get the config/model token from GitHub's matrix job display name."""
    config_files = re.findall(r"[^\s/(),]+\.yaml", job_name)
    if config_files:
        return config_files[-1]
    value = job_name.rsplit(" / ", 1)[-1].strip()
    return value if value.endswith(".yaml") else f"{value}.yaml"


def model_name(job_name: str) -> str:
    value = job_name.rsplit(" / ", 1)[-1].strip()
    return value.removesuffix(".yaml")


def fo_for_job(job_name: str, fo_map: dict[str, str]) -> str:
    config = config_name(job_name)
    if config in fo_map:
        return fo_map[config]

    lowered = config.casefold()
    for key, value in fo_map.items():
        if key.casefold() == lowered:
            return value
    return "\u672a\u914d\u7f6e"


def conclusion_label(job: dict) -> str | None:
    status = job.get("status")
    conclusion = job.get("conclusion")
    if status in {"queued", "waiting", "pending"}:
        return "\u6392\u961f\u4e2d"
    if conclusion == "failure":
        return "\u5931\u8d25"
    if conclusion == "cancelled":
        return "\u5df2\u53d6\u6d88"
    if conclusion == "skipped":
        return "\u672a\u6267\u884c（Skipped）"
    return None


def fetch_jobs(owner_repo: str, run_id: str) -> list[dict]:
    jobs: list[dict] = []
    page = 1
    while True:
        payload = github_get(
            f"https://api.github.com/repos/{owner_repo}/actions/runs/{run_id}/jobs"
            f"?per_page=100&page={page}"
        )
        page_jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
        jobs.extend(page_jobs)
        if len(page_jobs) < 100:
            return jobs
        page += 1


def is_excluded(job_name: str) -> bool:
    short_name = job_name.rsplit(" / ", 1)[-1].strip()
    return short_name in EXCLUDED_JOB_NAMES or job_name in EXCLUDED_JOB_NAMES


def main() -> int:
    parser = argparse.ArgumentParser(description="输出 GitHub Actions 异常 Job 报告")
    parser.add_argument("run_url", help="GitHub Actions workflow run 链接")
    args = parser.parse_args()

    try:
        owner_repo, run_id, _ = parse_run_url(args.run_url)
        fo_map = load_fo_map()
        run = fetch_run(owner_repo, run_id)
        jobs = fetch_jobs(owner_repo, run_id)
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    selected = []
    for job in jobs:
        name = str(job.get("name", "")).strip()
        status = conclusion_label(job)
        if not name or not status or is_excluded(name):
            continue
        selected.append((job, status))

    order = {"失败": 0, "已取消": 1, "排队中": 2, "未执行（Skipped）": 3}
    selected.sort(key=lambda item: (order[item[1]], item[0].get("name", "")))

    print(build_run_summary(run, jobs, owner_repo))
    print()

    for job, status in selected:
        name = job["name"].strip()
        model = model_name(name)
        fo = fo_for_job(name, fo_map)
        url = job.get("html_url") or f"https://github.com/{owner_repo}/actions/runs/{run_id}/job/{job['id']}"
        print(f"状态：{status}")
        print(f"job名称: {name}")
        print(f"模型: {model}")
        print(f"模型FO: {fo}")
        print(f"日志链接: {url}")
        print()

    if not selected:
        print("未发现符合条件的 Job。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
