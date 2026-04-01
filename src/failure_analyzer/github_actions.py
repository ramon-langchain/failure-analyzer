"""Helpers for GitHub Actions integration."""

from __future__ import annotations

import os
from pathlib import Path


REPORT_OUTPUT_NAME = "failure_analyzer_report_path"
PR_COMMENT_OUTPUT_NAME = "failure_analyzer_pr_comment_path"
ARTIFACT_DIR_OUTPUT_NAME = "failure_analyzer_artifact_dir"


def is_github_actions() -> bool:
    """Return True when running inside GitHub Actions."""
    return os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


def default_report_path() -> Path:
    """Choose a stable default report path for GitHub Actions runs."""
    configured = os.environ.get("FAILURE_ANALYZER_GITHUB_REPORT_PATH")
    if configured:
        return Path(configured).expanduser().resolve()

    runner_temp = os.environ.get("RUNNER_TEMP")
    if runner_temp:
        return Path(runner_temp).resolve() / "failure-analyzer" / "failure-analysis.md"

    workspace = os.environ.get("GITHUB_WORKSPACE")
    if workspace:
        return Path(workspace).resolve() / ".failure-analyzer" / "failure-analysis.md"

    return Path.cwd() / ".failure-analyzer" / "failure-analysis.md"


def default_pr_comment_path() -> Path:
    """Choose a stable default path for a generated PR comment body."""
    configured = os.environ.get("FAILURE_ANALYZER_GITHUB_PR_COMMENT_PATH")
    if configured:
        return Path(configured).expanduser().resolve()

    runner_temp = os.environ.get("RUNNER_TEMP")
    if runner_temp:
        return Path(runner_temp).resolve() / "failure-analyzer" / "pr-comment.md"

    workspace = os.environ.get("GITHUB_WORKSPACE")
    if workspace:
        return Path(workspace).resolve() / ".failure-analyzer" / "pr-comment.md"

    return Path.cwd() / ".failure-analyzer" / "pr-comment.md"


def default_artifact_dir() -> Path:
    """Choose a stable default directory for analyzer-generated artifacts."""
    configured = os.environ.get("FAILURE_ANALYZER_OUTPUT_DIR")
    if configured:
        return Path(configured).expanduser().resolve()

    runner_temp = os.environ.get("RUNNER_TEMP")
    if runner_temp:
        return Path(runner_temp).resolve() / "failure-analyzer" / "artifacts"

    workspace = os.environ.get("GITHUB_WORKSPACE")
    if workspace:
        return Path(workspace).resolve() / ".failure-analyzer" / "artifacts"

    return Path.cwd() / ".failure-analyzer" / "artifacts"


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
        handle.write("## failure-analyzer Report\n\n")
        handle.write(markdown.rstrip())
        handle.write("\n")
    return True


def should_defer_step_summary() -> bool:
    """Return True when summary publication should be handled by a later workflow step."""
    return os.environ.get("FAILURE_ANALYZER_DEFER_SUMMARY", "").lower() == "true"


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


def export_pr_comment_path(comment_path: Path) -> bool:
    """Expose the generated PR comment path as a GitHub Actions step output."""
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return False

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{PR_COMMENT_OUTPUT_NAME}={comment_path}\n")
    return True


def export_artifact_dir(artifact_dir: Path) -> bool:
    """Expose the analyzer artifact directory as a GitHub Actions step output."""
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return False

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{ARTIFACT_DIR_OUTPUT_NAME}={artifact_dir}\n")
    return True
