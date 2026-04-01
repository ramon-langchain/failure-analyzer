"""Optional LangSmith tracing configuration for failure-analyzer."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_LANGSMITH_PROJECT = "failure-analyzer"
LANGSMITH_KEY_ENV_NAMES = (
    "FAILURE_ANALYZER_LANGSMITH_API_KEY",
    "LANGSMITH_API_KEY",
)
LANGSMITH_PROJECT_ENV_NAMES = (
    "FAILURE_ANALYZER_LANGSMITH_PROJECT",
    "LANGSMITH_PROJECT",
)
LANGSMITH_ENDPOINT_ENV_NAMES = (
    "FAILURE_ANALYZER_LANGSMITH_ENDPOINT",
    "LANGSMITH_ENDPOINT",
)


@dataclass(slots=True)
class LangSmithTracingConfig:
    """Resolved LangSmith tracing configuration."""

    enabled: bool
    project: str | None = None
    endpoint: str | None = None


def _first_env(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def default_langsmith_project() -> str:
    """Choose a sensible default LangSmith project name."""
    github_repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if github_repository and "/" in github_repository:
        repo_name = github_repository.rsplit("/", 1)[-1].strip()
        if repo_name:
            return repo_name
    return DEFAULT_LANGSMITH_PROJECT


def configure_langsmith_tracing() -> LangSmithTracingConfig:
    """Enable LangSmith tracing when a tracing API key is available."""
    api_key = _first_env(LANGSMITH_KEY_ENV_NAMES)
    if not api_key:
        return LangSmithTracingConfig(enabled=False)

    os.environ["LANGSMITH_API_KEY"] = api_key

    endpoint = _first_env(LANGSMITH_ENDPOINT_ENV_NAMES)
    if endpoint:
        os.environ.setdefault("LANGSMITH_ENDPOINT", endpoint)

    project = _first_env(LANGSMITH_PROJECT_ENV_NAMES) or default_langsmith_project()
    os.environ.setdefault("LANGSMITH_PROJECT", project)
    os.environ.setdefault("LANGCHAIN_PROJECT", project)
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")

    return LangSmithTracingConfig(
        enabled=True,
        project=os.environ.get("LANGSMITH_PROJECT"),
        endpoint=os.environ.get("LANGSMITH_ENDPOINT"),
    )
