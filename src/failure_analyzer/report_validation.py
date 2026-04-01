"""Validation helpers for agent-authored Markdown reports."""

from __future__ import annotations

from dataclasses import dataclass
import difflib
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
LOG_EXCERPT_FENCE_PATTERN = re.compile(
    r"```logs\s+(?P<path>[^\s`:#]+(?:/[^\s`:#]+)*):(?P<start>\d+)(?:-(?P<end>\d+))?\n(?P<body>.*?)\n```",
    re.DOTALL,
)
CODE_FENCE_SPLIT_PATTERN = re.compile(r"(```.*?```)", re.DOTALL)
SYMBOL_REF_PATTERN = re.compile(r"(?P<tick>`)?(?P<symbol>[A-Z][A-Za-z0-9_]{4,})(?P=tick)?")
SYMBOL_STOPWORDS = {
    "Summary",
    "Root",
    "Cause",
    "Evidence",
    "Likely",
    "Direction",
    "Confidence",
    "GitHub",
    "Markdown",
    "Context",
    "Environment",
    "Output",
    "Artifact",
}


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


@dataclass(slots=True)
class SymbolLinkReminder:
    """A likely symbol mention that lacks a defining location."""

    symbols: list[str]

    @property
    def needed(self) -> bool:
        return bool(self.symbols)


def _read_source_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _spans_for(pattern: re.Pattern[str], text: str) -> list[tuple[int, int]]:
    return [match.span() for match in pattern.finditer(text)]


def _inside_spans(index: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= index < end for start, end in spans)


def detect_unlinked_symbols(markdown: str) -> SymbolLinkReminder:
    """Find likely code symbols in prose that do not include a defining location."""
    symbols: list[str] = []
    seen: set[str] = set()
    for part in CODE_FENCE_SPLIT_PATTERN.split(markdown):
        if part.startswith("```"):
            continue
        for match in SYMBOL_REF_PATTERN.finditer(part):
            symbol = match.group("symbol")
            if symbol in SYMBOL_STOPWORDS or symbol in seen:
                continue
            tick = match.group("tick")
            if not (
                tick
                or symbol.startswith(("Test", "Benchmark", "Example"))
                or re.search(r"[a-z][A-Z]", symbol)
                or "_" in symbol
            ):
                continue
            suffix = part[match.end() : match.end() + 48]
            if re.match(r"\s*\(\s*`[^`]+:\d+(?:-\d+)?`\s*\)", suffix):
                continue
            if re.match(r"\s*\([A-Za-z0-9_./-]+\.[A-Za-z0-9_./-]+:\d+(?:-\d+)?\s*\)", suffix):
                continue
            seen.add(symbol)
            symbols.append(symbol)
    return SymbolLinkReminder(symbols=symbols[:8])


def _find_exact_range(lines: list[str], excerpt_lines: list[str]) -> tuple[int, int] | None:
    if not excerpt_lines or len(excerpt_lines) > len(lines):
        return None
    window = len(excerpt_lines)
    for start_idx in range(0, len(lines) - window + 1):
        if lines[start_idx : start_idx + window] == excerpt_lines:
            start_line = start_idx + 1
            return start_line, start_line + window - 1
    return None


def _preview_diff(expected_lines: list[str], actual_lines: list[str]) -> str:
    diff = list(
        difflib.unified_diff(
            expected_lines,
            actual_lines,
            fromfile="expected",
            tofile="actual",
            lineterm="",
            n=1,
        )
    )
    trimmed = [line for line in diff[2:] if line]
    if not trimmed:
        return ""
    return " | ".join(trimmed[:4])


def _describe_excerpt_mismatch(
    *,
    container_label: str,
    path_label: str,
    start: int,
    end: int,
    available_lines: list[str],
    expected_lines: list[str],
    actual_lines: list[str],
) -> str:
    alternate_range = _find_exact_range(available_lines, actual_lines)
    if alternate_range is not None and alternate_range != (start, end):
        return (
            f"{container_label} matches {path_label}:{alternate_range[0]}-{alternate_range[1]} "
            f"instead of {path_label}:{start}-{end}"
        )
    expected_line_count = len(expected_lines)
    actual_line_count = len(actual_lines)

    if expected_line_count > 0 and actual_line_count == expected_line_count + 1:
        if actual_lines[:-1] == expected_lines:
            return (
                f"excerpt includes 1 extra trailing line; expected {path_label}:{start}-{end} "
                f"but body matches {path_label}:{start}-{end + 1}"
            )
        if actual_lines[1:] == expected_lines:
            return (
                f"excerpt includes 1 extra leading line; expected {path_label}:{start}-{end} "
                f"but body matches {path_label}:{start - 1}-{end}"
            )

    if actual_line_count + 1 == expected_line_count:
        if expected_lines[:-1] == actual_lines:
            return (
                f"excerpt is missing the final line from {path_label}:{start}-{end}; "
                f"body only covers {path_label}:{start}-{end - 1}"
            )
        if expected_lines[1:] == actual_lines:
            return (
                f"excerpt is missing the first line from {path_label}:{start}-{end}; "
                f"body only covers {path_label}:{start + 1}-{end}"
            )

    if [line.rstrip() for line in expected_lines] == [line.rstrip() for line in actual_lines]:
        return (
            f"{container_label} differs only by trailing whitespace from the referenced lines "
            f"{path_label}:{start}-{end}"
        )

    diff_preview = _preview_diff(expected_lines, actual_lines)
    if diff_preview:
        return (
            f"{container_label} does not exactly match the referenced lines {path_label}:{start}-{end}; "
            f"diff: {diff_preview}"
        )
    return f"{container_label} does not exactly match the referenced lines {path_label}:{start}-{end}"


def validate_report_markdown(
    markdown: str,
    *,
    result: TestRunResult,
    artifact_dir: Path,
) -> ValidationResult:
    """Validate source refs, artifact refs, and excerpt fences in a report."""
    issues: list[ValidationIssue] = []
    skip_spans = [
        *_spans_for(EXCERPT_FENCE_PATTERN, markdown),
        *_spans_for(LOG_EXCERPT_FENCE_PATTERN, markdown),
    ]

    for match in SOURCE_REF_PATTERN.finditer(markdown):
        if _inside_spans(match.start(), skip_spans):
            continue
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
        if _inside_spans(match.start(), skip_spans):
            continue
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
            expected_lines = lines[start - 1 : end]
            actual_lines = match.group("body").splitlines()
            issues.append(
                ValidationIssue(
                    kind="excerpt_fence",
                    reference=reference,
                    reason=_describe_excerpt_mismatch(
                        container_label="excerpt body",
                        path_label=resolved,
                        start=start,
                        end=end,
                        available_lines=lines,
                        expected_lines=expected_lines,
                        actual_lines=actual_lines,
                    ),
                )
            )

    for match in LOG_EXCERPT_FENCE_PATTERN.finditer(markdown):
        raw_path = match.group("path")
        start = int(match.group("start"))
        end = int(match.group("end") or start)
        reference = f"```logs {raw_path}:{start}-{end}```"
        artifact_path = (artifact_dir / raw_path).resolve()
        try:
            artifact_path.relative_to(artifact_dir.resolve())
        except ValueError:
            issues.append(
                ValidationIssue(
                    kind="log_excerpt_fence",
                    reference=reference,
                    reason="log excerpt path escapes FAILURE_ANALYZER_OUTPUT_DIR",
                )
            )
            continue
        if not artifact_path.exists() or not artifact_path.is_file():
            issues.append(
                ValidationIssue(
                    kind="log_excerpt_fence",
                    reference=reference,
                    reason=f"log excerpt file does not exist: {raw_path}",
                )
            )
            continue

        lines = artifact_path.read_text(encoding="utf-8").splitlines()
        if start < 1 or end < start or end > len(lines):
            issues.append(
                ValidationIssue(
                    kind="log_excerpt_fence",
                    reference=reference,
                    reason=f"line range {start}-{end} is outside artifact length {len(lines)}",
                )
            )
            continue

        expected = "\n".join(lines[start - 1 : end]).rstrip()
        actual = match.group("body").rstrip()
        if expected != actual:
            expected_lines = lines[start - 1 : end]
            actual_lines = match.group("body").splitlines()
            issues.append(
                ValidationIssue(
                    kind="log_excerpt_fence",
                    reference=reference,
                    reason=_describe_excerpt_mismatch(
                        container_label="log excerpt body",
                        path_label=raw_path,
                        start=start,
                        end=end,
                        available_lines=lines,
                        expected_lines=expected_lines,
                        actual_lines=actual_lines,
                    ),
                )
            )

    return ValidationResult(issues=issues)


def format_validation_feedback(validation: ValidationResult, report_path: Path) -> str:
    """Build a repair prompt for the agent."""
    current_report = report_path.read_text(encoding="utf-8") if report_path.exists() else "<missing>"
    issue_lines = "\n".join(
        f"- `{issue.reference}`: {issue.reason}"
        for issue in validation.issues
    )
    return (
        f"The Markdown report at `{report_path}` failed validation. "
        "Edit that file in place and fix only the invalid references or excerpt fences below.\n\n"
        "Current report contents:\n"
        "```markdown\n"
        f"{current_report}\n"
        "```\n\n"
        "Validation errors:\n"
        f"{issue_lines}\n\n"
        "Re-read the current report file before editing it. Make the smallest possible fixes and avoid broad rewrites. "
        "Prefer one precise edit per invalid reference or fence. "
        "Keep the report in GitHub-flavored Markdown. "
        "Use plain repo-relative source references like `path/to/file.go:55` or `path/to/file.go:55-70`. "
        "For validated source excerpts, use fences like ```go path/to/file.go#L55-L70. "
        "For validated runtime log excerpts, use fences like ```logs timed-output.log:12-18. "
        "If you cannot support a reference, remove or rewrite it rather than leaving it invalid."
    )


def format_symbol_link_feedback(reminder: SymbolLinkReminder, report_path: Path) -> str:
    """Build an optional prompt asking for symbol-definition links."""
    current_report = report_path.read_text(encoding="utf-8") if report_path.exists() else "<missing>"
    symbol_list = ", ".join(f"`{symbol}`" for symbol in reminder.symbols)
    return (
        f"The Markdown report at `{report_path}` looks valid, but it still mentions likely code symbols "
        f"without defining locations: {symbol_list}.\n\n"
        "Current report contents:\n"
        "```markdown\n"
        f"{current_report}\n"
        "```\n\n"
        "If these are real code symbols and you can locate them confidently, edit the report in place and add "
        "their defining source locations using the preferred format `SymbolName` (`path/to/file.ext:123`). "
        "If any listed item is not actually a code symbol, or you cannot locate it confidently, you may leave "
        "the report unchanged. Do not rewrite unrelated parts of the report."
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
    def replace_log_excerpt(match: re.Match[str]) -> str:
        reference = (
            f"```logs {match.group('path')}:{match.group('start')}"
            f"{f'-{match.group('end')}' if match.group('end') else ''}```"
        )
        if any(
            issue.kind == "log_excerpt_fence" and issue.reference == reference
            for issue in validation.issues
        ):
            return f"```text\n{match.group('body')}\n```"
        return match.group(0)

    degraded = LOG_EXCERPT_FENCE_PATTERN.sub(replace_log_excerpt, degraded)
    if validation.issues:
        degraded = degraded.rstrip() + (
            "\n\n> Note: Some source references or excerpts could not be validated automatically "
            "and were downgraded to plain text.\n"
        )
    return degraded
