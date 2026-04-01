"""Typed models for test execution and failure analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class TestRunResult:
    """Captured output and metadata from a wrapped test command."""

    __test__ = False

    command: tuple[str, ...]
    cwd: Path
    exit_code: int
    stdout: str
    stderr: str
    started_at: datetime
    finished_at: datetime
    environment: dict[str, str] = field(default_factory=dict)
    timed_output_path: Path | None = None

    @property
    def combined_output(self) -> str:
        """Return stdout and stderr in a stable labeled format."""
        sections = [
            "### STDOUT",
            "",
            self.stdout or "<empty>",
            "",
            "### STDERR",
            "",
            self.stderr or "<empty>",
        ]
        return "\n".join(sections)


@dataclass(slots=True)
class AnalysisRequest:
    """Inputs passed into the failure-analysis agent."""

    __test__ = False

    command: tuple[str, ...]
    repo_root: Path
    exit_code: int
    stdout: str
    stderr: str
    combined_output: str
    environment: dict[str, str] = field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    timed_output_path: Path | None = None
    timed_output_artifact_ref: str | None = None
    max_output_bytes: int = 120_000
    enable_shell_analysis: bool = True
    allow_rerun: bool = False
    thinking_effort: str = "medium"


@dataclass(slots=True)
class AnalysisResult:
    """Final failure-analysis report plus metadata."""

    __test__ = False

    report_markdown: str
    report_path: Path | None = None
    used_truncation: bool = False
    was_streamed: bool = False
