"""Prompt and report formatting helpers."""

from __future__ import annotations

import os
import shlex
from collections.abc import Mapping
from datetime import datetime
from importlib.resources import files
from textwrap import dedent

from failure_analyzer.models import TestRunResult


PROMPT_RESOURCE = "ci_failure_analysis_system.md"
REDACTED_ENV_MARKERS = ("KEY", "API", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
STREAM_FORMAT_LEGEND = "`+<milliseconds>ms <stream> <text>`, where `O` means stdout and `E` means stderr."


def load_system_prompt() -> str:
    """Load the analysis system prompt from the packaged prompt resource."""
    return (
        files("failure_analyzer.prompts")
        .joinpath(PROMPT_RESOURCE)
        .read_text(encoding="utf-8")
        .strip()
    )


def format_exact_command(command: tuple[str, ...] | list[str]) -> str:
    """Render a shell-safe command string for display."""
    return shlex.join(command)


def format_timestamp(timestamp: datetime | None) -> str:
    """Render an ISO8601 UTC timestamp."""
    if timestamp is None:
        return "<unknown>"
    return timestamp.isoformat()


def duration_milliseconds(started_at: datetime | None, finished_at: datetime | None) -> int | None:
    """Return the command duration in milliseconds."""
    if started_at is None or finished_at is None:
        return None
    return max(0, int((finished_at - started_at).total_seconds() * 1000))


def redact_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Redact sensitive environment values."""
    redacted: dict[str, str] = {}
    for name, value in environment.items():
        upper_name = name.upper()
        if any(marker in upper_name for marker in REDACTED_ENV_MARKERS):
            redacted[name] = "<redacted>"
        else:
            redacted[name] = value
    return redacted


def format_environment_block(environment: Mapping[str, str]) -> str:
    """Format the environment as sorted KEY=VALUE lines."""
    if not environment:
        return "<empty>"

    redacted = redact_environment(environment)
    lines = [f"{name}={redacted[name]}" for name in sorted(redacted)]
    return "\n".join(lines)


def build_run_context_markdown(result: TestRunResult) -> str:
    """Build the deterministic run-context appendix added to reports."""
    duration_ms = duration_milliseconds(result.started_at, result.finished_at)
    duration_text = f"{duration_ms} ms" if duration_ms is not None else "<unknown>"
    timed_output_path = str(result.timed_output_path) if result.timed_output_path else "<not captured>"
    environment_block = format_environment_block(result.environment)

    return dedent(
        f"""\
        ## Run Context

        - Exact command: `{format_exact_command(list(result.command))}`
        - Working directory: `{result.cwd}`
        - Started at (UTC): `{format_timestamp(result.started_at)}`
        - Finished at (UTC): `{format_timestamp(result.finished_at)}`
        - Duration: `{duration_text}`
        - Timed output file: `{timed_output_path}`
        - Timed output format: {STREAM_FORMAT_LEGEND}

        ### Environment (redacted)

        ```text
        {environment_block}
        ```
        """
    ).strip()


def append_run_context(report: str, result: TestRunResult) -> str:
    """Append deterministic run context to a Markdown report."""
    context = build_run_context_markdown(result)
    if not report.strip():
        return f"{context}\n"
    return f"{report.rstrip()}\n\n{context}\n"


def build_missing_credentials_summary(secret_names: tuple[str, ...]) -> str:
    """Return a short GitHub Actions summary for missing provider credentials."""
    secret_list = "\n".join(f"- `{name}`" for name in secret_names)
    return dedent(
        f"""\
        ## failure-analyzer setup required

        No supported model credentials were configured for this workflow run.

        Add one repository or organization Actions secret with one of these exact names:

        {secret_list}

        Where to add it:
        1. Open the caller repository on GitHub.
        2. Go to `Settings` -> `Secrets and variables` -> `Actions`.
        3. Create a repository secret with one of the names above.
        4. Re-run this workflow.
        """
    ).strip()


def has_any_provider_credentials(secret_names: tuple[str, ...]) -> bool:
    """Return True when any supported provider credential is configured."""
    return any(os.environ.get(name) for name in secret_names)
