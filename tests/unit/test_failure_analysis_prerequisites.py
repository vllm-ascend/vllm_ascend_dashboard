import subprocess
from pathlib import Path

import pytest

from agent import agent_tools
from failure_analysis.failure_analysis import FailureAnalysisService
from infrastructure.clients import github_cache
from infrastructure.clients.git_mirror import GitMirrorRepository


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
        tmp_path / "worktrees" / "vllm-project_vllm-ascend" / "main"
    ).resolve()
    assert agent_tools._agent_repo_path("vllm") == (
        tmp_path / "worktrees" / "vllm-project_vllm" / "main"
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


def test_analysis_uses_existing_repository_snapshots_without_network(monkeypatch, tmp_path):
    class FakeCache:
        def __init__(self, name: str):
            self.cache_dir = Path(tmp_path) / name
            (self.cache_dir / ".git").mkdir(parents=True)
            self.clone_url = f"https://example.test/{name}.git"

        def _is_repo_cloned(self):
            return True

        def pull(self):
            raise AssertionError("analysis must not pull an existing snapshot")

        def clone(self):
            raise AssertionError("analysis must not clone an existing snapshot")

        def fetch_full_history(self):
            raise AssertionError("analysis must not fetch an existing snapshot")

    ascend = FakeCache("ascend")
    vllm = FakeCache("vllm")
    monkeypatch.setattr(github_cache, "get_github_cache", lambda: ascend)
    monkeypatch.setattr(github_cache, "get_vllm_cache", lambda: vllm)

    assert github_cache.ensure_analysis_repos_ready(update=False) == {
        "vllm_ascend": str(ascend.cache_dir.resolve()),
        "vllm": str(vllm.cache_dir.resolve()),
    }


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


def test_bare_mirror_reads_refs_and_isolates_worktrees(tmp_path):
    upstream = tmp_path / "upstream"

    def git(*args, cwd=upstream):
        return subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
        )

    upstream.mkdir()
    git("init", "-b", "main")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")
    (upstream / "value.txt").write_text("main-v1", encoding="utf-8")
    git("add", "value.txt")
    git("commit", "-m", "main v1")
    git("checkout", "-b", "releases/v1")
    (upstream / "value.txt").write_text("release-v1", encoding="utf-8")
    git("commit", "-am", "release v1")
    git("checkout", "main")

    mirror = GitMirrorRepository(
        storage_root=tmp_path / "cache",
        owner="example",
        repo="project",
        clone_url=str(upstream),
    )
    assert mirror.bootstrap() is True
    assert mirror.read_file("main", "value.txt") == "main-v1"
    assert mirror.read_file("releases/v1", "value.txt") == "release-v1"
    assert mirror.remote_branches("releases/") == ["releases/v1"]

    release_tree = mirror.isolated_worktree("releases/v1", "nightly-releases-v1")
    assert release_tree is not None
    assert (release_tree / "value.txt").read_text(encoding="utf-8") == "release-v1"
    assert (mirror.main_worktree / "value.txt").read_text(encoding="utf-8") == "main-v1"

    (upstream / "value.txt").write_text("main-v2", encoding="utf-8")
    git("commit", "-am", "main v2")
    assert mirror.refresh() is True
    assert mirror.read_file("main", "value.txt") == "main-v2"
    assert (release_tree / "value.txt").read_text(encoding="utf-8") == "release-v1"
