"""Helpers for loading optional invocation context into the system prompt."""

from __future__ import annotations

import os
from pathlib import Path


CONTEXT_FILE_ENV_VAR = "FAILURE_ANALYZER_CONTEXT_FILE"


def load_invocation_context() -> str | None:
    """Load additional invocation context from a configured file path."""
    configured = os.environ.get(CONTEXT_FILE_ENV_VAR, "").strip()
    if not configured:
        return None
    path = Path(configured).expanduser().resolve()
    if not path.exists() or not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def append_invocation_context(system_prompt: str, invocation_context: str | None) -> str:
    """Append runtime-built invocation context as a tagged prompt section."""
    if not invocation_context or not invocation_context.strip():
        return system_prompt
    return (
        f"{system_prompt.rstrip()}\n\n"
        "<invocation_context>\n"
        "The following context was collected from the current execution environment. "
        "Treat it as additional factual context about how this run was invoked.\n\n"
        f"{invocation_context.strip()}\n"
        "</invocation_context>\n"
    )
