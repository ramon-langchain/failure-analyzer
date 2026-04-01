"""Helpers for GitHub Actions integration."""

from __future__ import annotations

import os
from pathlib import Path


REPORT_OUTPUT_NAME = "test_analyzer_report_path"


def is_github_actions() -> bool:
    """Return True when running inside GitHub Actions."""
    return os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


def default_report_path() -> Path:
    """Choose a stable default report path for GitHub Actions runs."""
    configured = os.environ.get("TEST_ANALYZER_GITHUB_REPORT_PATH")
    if configured:
        return Path(configured).expanduser().resolve()

    runner_temp = os.environ.get("RUNNER_TEMP")
    if runner_temp:
        return Path(runner_temp).resolve() / "test-analyzer" / "failure-analysis.md"

    workspace = os.environ.get("GITHUB_WORKSPACE")
    if workspace:
        return Path(workspace).resolve() / ".test-analyzer" / "failure-analysis.md"

    return Path.cwd() / ".test-analyzer" / "failure-analysis.md"


def append_step_summary(markdown: str) -> bool:
    """Append the report to the GitHub Actions step summary if available."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return False

    path = Path(summary_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        if path.stat().st_size > 0:
            handle.write("\n\n")
        handle.write("## test-analyzer Report\n\n")
        handle.write(markdown.rstrip())
        handle.write("\n")
    return True


def export_report_path(report_path: Path) -> bool:
    """Expose the report path as a GitHub Actions step output if available."""
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return False

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{REPORT_OUTPUT_NAME}={report_path}\n")
    return True
