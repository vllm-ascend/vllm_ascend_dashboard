import subprocess
from pathlib import Path

import pytest

from agent import agent_tools
from failure_analysis.failure_analysis import FailureAnalysisService
from infrastructure.clients import github_cache


def test_missing_failure_facts_blocks_completed_report():
    validation = {
        "findings": [
            {"severity": "error", "code": "missing_failure_facts"},
            {"severity": "error", "code": "missing_hypotheses"},
        ]
    }

    assert FailureAnalysisService._blocking_investigation_findings(validation) == [
        {"severity": "error", "code": "missing_failure_facts"}
    ]


def test_agent_can_resolve_both_analysis_repositories(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_tools.settings, "DATA_DIR", str(tmp_path))
    monkeypatch.delenv("AGENT_REPO_PATH", raising=False)
    monkeypatch.delenv("AGENT_VLLM_REPO_PATH", raising=False)

    assert agent_tools._agent_repo_path("vllm_ascend") == (
        tmp_path / "repos" / "vllm-project_vllm-ascend"
    ).resolve()
    assert agent_tools._agent_repo_path("vllm") == (
        tmp_path / "repos" / "vllm-project_vllm"
    ).resolve()

    with pytest.raises(ValueError):
        agent_tools._agent_repo_path("unknown")


def test_analysis_repository_preparation_requires_both_repositories(monkeypatch, tmp_path):
    class FakeCache:
        def __init__(self, name: str, ready: bool):
            self.name = name
            self.ready = ready
            self.cache_dir = Path(tmp_path) / name
            self.clone_url = f"https://example.test/{name}.git"

        def pull(self):
            return self.ready

        def clone(self):
            return self.ready

        def _is_repo_cloned(self):
            return self.ready

        def fetch_full_history(self):
            return self.ready

    monkeypatch.setattr(github_cache, "get_github_cache", lambda: FakeCache("ascend", True))
    monkeypatch.setattr(github_cache, "get_vllm_cache", lambda: FakeCache("vllm", False))

    with pytest.raises(RuntimeError, match="vllm"):
        github_cache.ensure_analysis_repos_ready()


def test_github_cache_pull_resets_divergent_cache(monkeypatch, tmp_path):
    cache = github_cache.GitHubLocalCache(
        cache_dir=str(tmp_path / "repo"),
        owner="vllm-project",
        repo="vllm",
    )
    (cache.cache_dir / ".git").mkdir(parents=True)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[:3] == ["git", "pull", "origin"]:
            raise subprocess.CalledProcessError(
                128,
                args,
                stderr=b"fatal: Need to specify how to reconcile divergent branches.",
            )
        return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert cache.pull() is True
    assert ["git", "reset", "--hard", "origin/main"] in calls
