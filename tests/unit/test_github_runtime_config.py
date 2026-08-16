"""Tests for shared GitHub configuration propagation."""
from __future__ import annotations

from infrastructure.core import app_runtime_config, github_config
from infrastructure.core.config import settings
from infrastructure.core.security import encrypt_api_key


def test_apply_runtime_config_decrypts_and_updates_process_settings(monkeypatch) -> None:
    token = "github_pat_test_runtime_token_1234567890"
    monkeypatch.setattr(settings, "GITHUB_OWNER", "bootstrap-owner")
    monkeypatch.setattr(settings, "GITHUB_REPO", "bootstrap-repo")
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "bootstrap-token")

    applied = github_config._apply_runtime_config(
        {
            "owner": "configured-owner",
            "repo": "configured-repo",
            "token_encrypted": encrypt_api_key(token),
        }
    )

    assert applied is True
    assert settings.GITHUB_OWNER == "configured-owner"
    assert settings.GITHUB_REPO == "configured-repo"
    assert settings.GITHUB_TOKEN == token


def test_invalid_runtime_token_does_not_replace_bootstrap_token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "bootstrap-token")

    applied = github_config._apply_runtime_config(
        {"token_encrypted": "not-a-valid-encrypted-token"}
    )

    assert applied is False
    assert settings.GITHUB_TOKEN == "bootstrap-token"


def test_app_runtime_config_updates_process_settings(monkeypatch) -> None:
    monkeypatch.setattr(settings, "LOG_LEVEL", "INFO")
    monkeypatch.setattr(settings, "DEBUG", True)

    applied = app_runtime_config._apply_runtime_config(
        {"log_level": "warning", "debug": False}
    )

    assert applied == {"log_level": "WARNING", "debug": False}
    assert settings.LOG_LEVEL == "WARNING"
    assert settings.DEBUG is False
