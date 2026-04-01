"""Validation helpers for agent-authored Markdown reports."""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path

from failure_analyzer.models import TestRunResult
from failure_analyzer.prompting import resolve_repo_relative_path


SOURCE_REF_PATTERN = re.compile(
    r"(?P<tick>`)?(?P<path>(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+\.[A-Za-z0-9._-]+|/[A-Za-z0-9._/\-]+(?:\.[A-Za-z0-9._-]+)):(?P<line>\d+)(?:-(?P<end_line>\d+))?(?P=tick)?"
)
ARTIFACT_REF_PATTERN = re.compile(
    r"(?P<tick>`)?artifact:(?P<path>[A-Za-z0-9._/\-]+)(?::(?P<line>\d+)(?:-(?P<end_line>\d+))?)?(?P=tick)?"
)
EXCERPT_FENCE_PATTERN = re.compile(
    r"```(?P<language>[A-Za-z0-9_+-]+)\s+(?P<path>[^\s`#]+)#(?:L)?(?P<start>\d+)(?:-L?(?P<end>\d+))?\n(?P<body>.*?)\n```",
    re.DOTALL,
)


@dataclass(slots=True)
class ValidationIssue:
    """A single report validation error."""

    kind: str
    reference: str
    reason: str


@dataclass(slots=True)
class ValidationResult:
    """Validation outcome for a Markdown report."""

    issues: list[ValidationIssue]

    @property
    def is_valid(self) -> bool:
        return not self.issues


def _read_source_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def validate_report_markdown(
    markdown: str,
    *,
    result: TestRunResult,
    artifact_dir: Path,
) -> ValidationResult:
    """Validate source refs, artifact refs, and excerpt fences in a report."""
    issues: list[ValidationIssue] = []

    for match in SOURCE_REF_PATTERN.finditer(markdown):
        if match.start() >= 9 and markdown[match.start() - 9 : match.start()] == "artifact:":
            continue
        reference = match.group(0)
        resolved = resolve_repo_relative_path(match.group("path"), result)
        if resolved is None:
            issues.append(
                ValidationIssue(
                    kind="source_reference",
                    reference=reference,
                    reason="path does not resolve under the current workspace",
                )
            )
            continue
        source_path = Path(result.environment.get("GITHUB_WORKSPACE", result.cwd)).resolve() / resolved
        if not source_path.exists():
            issues.append(
                ValidationIssue(
                    kind="source_reference",
                    reference=reference,
                    reason=f"file does not exist: {resolved}",
                )
            )
            continue
        if not source_path.is_file():
            issues.append(
                ValidationIssue(
                    kind="source_reference",
                    reference=reference,
                    reason=f"path is not a file: {resolved}",
                )
            )
            continue

        lines = _read_source_lines(source_path)
        start = int(match.group("line"))
        end = int(match.group("end_line") or start)
        if start < 1 or end < start or end > len(lines):
            issues.append(
                ValidationIssue(
                    kind="source_reference",
                    reference=reference,
                    reason=f"line range {start}-{end} is outside file length {len(lines)}",
                )
            )

    for match in ARTIFACT_REF_PATTERN.finditer(markdown):
        reference = match.group(0)
        stripped_path = match.group("path").rstrip(".,;:!?")
        artifact_path = (artifact_dir / stripped_path).resolve()
        try:
            artifact_path.relative_to(artifact_dir.resolve())
        except ValueError:
            issues.append(
                ValidationIssue(
                    kind="artifact_reference",
                    reference=reference,
                    reason="artifact path escapes FAILURE_ANALYZER_OUTPUT_DIR",
                )
            )
            continue
        if not artifact_path.exists():
            issues.append(
                ValidationIssue(
                    kind="artifact_reference",
                    reference=reference,
                    reason=f"artifact does not exist: {stripped_path}",
                )
            )
            continue
        line = match.group("line")
        end_line = match.group("end_line") or line
        if line:
            lines = artifact_path.read_text(encoding="utf-8").splitlines()
            start = int(line)
            end = int(end_line or line)
            if start < 1 or end < start or end > len(lines):
                issues.append(
                    ValidationIssue(
                        kind="artifact_reference",
                        reference=reference,
                        reason=f"line range {start}-{end} is outside artifact length {len(lines)}",
                    )
                )

    for match in EXCERPT_FENCE_PATTERN.finditer(markdown):
        language = match.group("language")
        raw_path = match.group("path")
        start = int(match.group("start"))
        end = int(match.group("end") or start)
        reference = f"```{language} {raw_path}#L{start}-L{end}```"
        resolved = resolve_repo_relative_path(raw_path, result)
        if resolved is None:
            issues.append(
                ValidationIssue(
                    kind="excerpt_fence",
                    reference=reference,
                    reason="excerpt path does not resolve under the current workspace",
                )
            )
            continue
        source_path = Path(result.environment.get("GITHUB_WORKSPACE", result.cwd)).resolve() / resolved
        if not source_path.exists() or not source_path.is_file():
            issues.append(
                ValidationIssue(
                    kind="excerpt_fence",
                    reference=reference,
                    reason=f"excerpt file does not exist: {resolved}",
                )
            )
            continue

        lines = _read_source_lines(source_path)
        if start < 1 or end < start or end > len(lines):
            issues.append(
                ValidationIssue(
                    kind="excerpt_fence",
                    reference=reference,
                    reason=f"line range {start}-{end} is outside file length {len(lines)}",
                )
            )
            continue

        expected = "\n".join(lines[start - 1 : end]).rstrip()
        actual = match.group("body").rstrip()
        if expected != actual:
            issues.append(
                ValidationIssue(
                    kind="excerpt_fence",
                    reference=reference,
                    reason="excerpt body does not exactly match the referenced file lines",
                )
            )

    return ValidationResult(issues=issues)


def format_validation_feedback(validation: ValidationResult, report_path: Path) -> str:
    """Build a repair prompt for the agent."""
    issue_lines = "\n".join(
        f"- `{issue.reference}`: {issue.reason}"
        for issue in validation.issues
    )
    return (
        f"The Markdown report at `{report_path}` failed validation. "
        "Edit that file in place and fix only the invalid references or excerpt fences below.\n\n"
        "Validation errors:\n"
        f"{issue_lines}\n\n"
        "Keep the report in GitHub-flavored Markdown. "
        "Use plain repo-relative source references like `path/to/file.go:55` or `path/to/file.go:55-70`. "
        "For validated source excerpts, use fences like ```go path/to/file.go#L55-L70. "
        "If you cannot support a reference, remove or rewrite it rather than leaving it invalid."
    )


def degrade_invalid_markdown(markdown: str, validation: ValidationResult) -> str:
    """Remove invalid linkability metadata after repair attempts are exhausted."""
    degraded = markdown
    for issue in validation.issues:
        if issue.kind == "artifact_reference":
            degraded = degraded.replace(issue.reference, issue.reference.replace("`", ""))
        elif issue.kind == "source_reference":
            degraded = degraded.replace(issue.reference, issue.reference.replace("`", ""))

    def replace_excerpt(match: re.Match[str]) -> str:
        reference = (
            f"```{match.group('language')} {match.group('path')}#L{match.group('start')}"
            f"{f'-L{match.group('end')}' if match.group('end') else ''}```"
        )
        if any(
            issue.kind == "excerpt_fence" and issue.reference == reference
            for issue in validation.issues
        ):
            return f"```{match.group('language')}\n{match.group('body')}\n```"
        return match.group(0)

    degraded = EXCERPT_FENCE_PATTERN.sub(replace_excerpt, degraded)
    if validation.issues:
        degraded = degraded.rstrip() + (
            "\n\n> Note: Some source references or excerpts could not be validated automatically "
            "and were downgraded to plain text.\n"
        )
    return degraded
