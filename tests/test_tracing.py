from __future__ import annotations

import os

from failure_analyzer.tracing import (
    DEFAULT_LANGSMITH_PROJECT,
    configure_langsmith_tracing,
    default_langsmith_project,
)


def test_configure_langsmith_tracing_is_disabled_without_key(monkeypatch) -> None:
    monkeypatch.delenv("FAILURE_ANALYZER_LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)

    config = configure_langsmith_tracing()

    assert config.enabled is False
    assert os.environ.get("LANGSMITH_TRACING") is None
    assert os.environ.get("LANGCHAIN_TRACING_V2") is None


def test_configure_langsmith_tracing_prefers_prefixed_env(monkeypatch) -> None:
    monkeypatch.setenv("FAILURE_ANALYZER_LANGSMITH_API_KEY", "prefixed-key")
    monkeypatch.setenv("LANGSMITH_API_KEY", "fallback-key")
    monkeypatch.setenv("FAILURE_ANALYZER_LANGSMITH_PROJECT", "prefixed-project")
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    monkeypatch.delenv("LANGCHAIN_PROJECT", raising=False)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)

    config = configure_langsmith_tracing()

    assert config.enabled is True
    assert config.project == "prefixed-project"
    assert os.environ["LANGSMITH_API_KEY"] == "prefixed-key"
    assert os.environ["LANGSMITH_PROJECT"] == "prefixed-project"
    assert os.environ["LANGCHAIN_PROJECT"] == "prefixed-project"
    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"


def test_configure_langsmith_tracing_uses_default_project(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "standard-key")
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_LANGSMITH_PROJECT", raising=False)
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    monkeypatch.delenv("LANGCHAIN_PROJECT", raising=False)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)

    config = configure_langsmith_tracing()

    assert config.enabled is True
    assert config.project == DEFAULT_LANGSMITH_PROJECT
    assert os.environ["LANGSMITH_PROJECT"] == DEFAULT_LANGSMITH_PROJECT


def test_default_langsmith_project_uses_github_repo_basename(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "ramon-langchain/failure-analyzer")

    assert default_langsmith_project() == "failure-analyzer"


def test_configure_langsmith_tracing_uses_github_repo_basename(monkeypatch) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "standard-key")
    monkeypatch.setenv("GITHUB_REPOSITORY", "ramon-langchain/demo-repo")
    monkeypatch.delenv("FAILURE_ANALYZER_LANGSMITH_PROJECT", raising=False)
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    monkeypatch.delenv("LANGCHAIN_PROJECT", raising=False)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)

    config = configure_langsmith_tracing()

    assert config.enabled is True
    assert config.project == "demo-repo"
    assert os.environ["LANGSMITH_PROJECT"] == "demo-repo"
