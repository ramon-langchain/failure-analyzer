"""Prompt and report formatting helpers."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from collections.abc import Mapping
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from textwrap import dedent

from failure_analyzer.models import TestRunResult


PROMPT_RESOURCE = "ci_failure_analysis_system.md"
PR_COMMENT_PROMPT_RESOURCE = "ci_failure_pr_comment_system.md"
REDACTED_ENV_MARKERS = ("KEY", "API", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
STREAM_FORMAT_LEGEND = "`+<milliseconds>ms <stream> <text>`, where `O` means stdout and `E` means stderr."
IMPORTANT_ENV_NAMES = (
    "CI",
    "GITHUB_ACTIONS",
    "GITHUB_WORKFLOW",
    "GITHUB_WORKFLOW_REF",
    "GITHUB_WORKFLOW_SHA",
    "GITHUB_RUN_ID",
    "GITHUB_RUN_NUMBER",
    "GITHUB_RUN_ATTEMPT",
    "GITHUB_JOB",
    "GITHUB_REF",
    "GITHUB_SHA",
    "RUNNER_OS",
    "RUNNER_ARCH",
    "RUNNER_NAME",
    "FAILURE_ANALYZER_MODEL",
    "FAILURE_ANALYZER_COMMAND",
    "FAILURE_ANALYZER_CAN_READ_ACTIONS",
    "FAILURE_ANALYZER_FILES_BASE",
    "FAILURE_ANALYZER_OUTPUT_DIR",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_CLOUD_PROJECT",
    "FAILURE_ANALYZER_OPENAI_API_KEY",
    "FAILURE_ANALYZER_ANTHROPIC_API_KEY",
    "FAILURE_ANALYZER_GOOGLE_API_KEY",
    "FAILURE_ANALYZER_GOOGLE_CLOUD_PROJECT",
)
_CODE_FENCE_SPLIT_PATTERN = re.compile(r"(```.*?```)", re.DOTALL)
_FILE_LINE_PATTERN = re.compile(
    r"(?P<tick>`)?(?P<path>(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+\.[A-Za-z0-9._-]+|/[A-Za-z0-9._/\-]+(?:\.[A-Za-z0-9._-]+)):(?P<line>\d+)(?:-(?P<end_line>\d+))?(?P=tick)?"
)
_ARTIFACT_REF_PATTERN = re.compile(
    r"(?P<tick>`)?artifact:(?P<path>[A-Za-z0-9._/\-]+)(?::(?P<line>\d+)(?:-(?P<end_line>\d+))?)?(?P=tick)?"
)


def load_system_prompt() -> str:
    """Load the analysis system prompt from the packaged prompt resource."""
    return (
        files("failure_analyzer.prompts")
        .joinpath(PROMPT_RESOURCE)
        .read_text(encoding="utf-8")
        .strip()
    )


def load_pr_comment_prompt() -> str:
    """Load the PR comment system prompt from the packaged prompt resource."""
    return (
        files("failure_analyzer.prompts")
        .joinpath(PR_COMMENT_PROMPT_RESOURCE)
        .read_text(encoding="utf-8")
        .strip()
    )


def append_custom_instructions(system_prompt: str, custom_instructions: str | None) -> str:
    """Append user-provided instructions in a higher-priority tagged section."""
    if not custom_instructions or not custom_instructions.strip():
        return system_prompt

    return (
        f"{system_prompt.rstrip()}\n\n"
        "<user_override_instructions>\n"
        "These user-provided instructions supersede any conflicting built-in instructions above.\n\n"
        f"{custom_instructions.strip()}\n"
        "</user_override_instructions>\n"
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


def format_important_environment(environment: Mapping[str, str]) -> str:
    """Format a high-signal subset of environment variables."""
    if not environment:
        return "<empty>"

    redacted = redact_environment(environment)
    lines = [
        f"- `{name}={redacted[name]}`"
        for name in IMPORTANT_ENV_NAMES
        if name in redacted and redacted[name] != ""
    ]
    return "\n".join(lines) if lines else "<empty>"


def read_timed_output_excerpt(path: Path | None, *, head_lines: int = 12, tail_lines: int = 12) -> str:
    """Return a compact excerpt from the timed output log."""
    if path is None:
        return "<not captured>"
    if not path.exists():
        return f"<missing: {path}>"

    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return "<empty>"
    if len(lines) <= head_lines + tail_lines:
        return "\n".join(lines)

    head = lines[:head_lines]
    tail = lines[-tail_lines:]
    return "\n".join([*head, "...", *tail])


def build_run_context_markdown(result: TestRunResult) -> str:
    """Build the deterministic run-context appendix added to reports."""
    duration_ms = duration_milliseconds(result.started_at, result.finished_at)
    duration_text = f"{duration_ms} ms" if duration_ms is not None else "<unknown>"
    timed_output_path = str(result.timed_output_path) if result.timed_output_path else "<not captured>"
    important_environment = format_important_environment(result.environment)
    environment_block = format_environment_block(result.environment)
    timed_output_excerpt = read_timed_output_excerpt(result.timed_output_path)
    return (
        "## Run Context\n\n"
        "| Field | Value |\n"
        "| --- | --- |\n"
        f"| Exact command | `{format_exact_command(list(result.command))}` |\n"
        f"| Working directory | `{result.cwd}` |\n"
        f"| Started at (UTC) | `{format_timestamp(result.started_at)}` |\n"
        f"| Finished at (UTC) | `{format_timestamp(result.finished_at)}` |\n"
        f"| Duration | `{duration_text}` |\n"
        f"| Timed output file | `{timed_output_path}` |\n"
        f"| Timed output format | {STREAM_FORMAT_LEGEND} |\n\n"
        "### Important Environment (redacted)\n\n"
        f"{important_environment}\n\n"
        "<details>\n"
        "<summary>Timed Output Excerpt</summary>\n\n"
        "```text\n"
        f"{timed_output_excerpt}\n"
        "```\n"
        "</details>\n\n"
        "<details>\n"
        "<summary>Full Environment (redacted)</summary>\n\n"
        "```text\n"
        f"{environment_block}\n"
        "```\n"
        "</details>"
    )


def append_run_context(report: str, result: TestRunResult) -> str:
    """Append deterministic run context to a Markdown report."""
    context = build_run_context_markdown(result)
    if not report.strip():
        return f"{context}\n"
    return f"{report.rstrip()}\n\n{context}\n"


def resolve_repo_relative_path(raw_path: str, result: TestRunResult) -> str | None:
    """Resolve a referenced file path to a repo-relative path when possible."""
    workspace = result.environment.get("GITHUB_WORKSPACE")
    cwd = result.cwd.resolve()
    workspace_root = Path(workspace).resolve() if workspace else cwd
    cwd_relative = None
    try:
        cwd_relative = cwd.relative_to(workspace_root)
    except ValueError:
        cwd_relative = None

    candidate = Path(raw_path)
    candidate_paths: list[Path] = []
    if candidate.is_absolute():
        candidate_paths.append(candidate.resolve())
    else:
        candidate_paths.append((cwd / candidate).resolve())
        if cwd_relative is not None:
            candidate_paths.append((workspace_root / cwd_relative / candidate).resolve())
        candidate_paths.append((workspace_root / candidate).resolve())

    seen: set[Path] = set()
    for path in candidate_paths:
        if path in seen:
            continue
        seen.add(path)
        try:
            relative = path.relative_to(workspace_root)
        except ValueError:
            continue
        if _is_not_git_tracked(relative.as_posix(), workspace_root):
            continue
        return relative.as_posix()
    return None


def _is_not_git_tracked(repo_relative_path: str, workspace_root: Path) -> bool:
    """Return True when git does not consider a workspace-relative path tracked."""
    git_dir = workspace_root / ".git"
    if not git_dir.exists():
        return False
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", repo_relative_path],
            cwd=workspace_root,
            check=False,
            capture_output=True,
            text=False,
        )
    except OSError:
        return False
    return result.returncode != 0


def read_artifact_excerpt(
    artifact_dir: Path,
    artifact_path: str,
    *,
    start_line: int,
    end_line: int,
) -> str | None:
    """Read a line-ranged excerpt from an uploaded artifact file."""
    path = (artifact_dir / artifact_path).resolve()
    try:
        path.relative_to(artifact_dir.resolve())
    except ValueError:
        return None
    if not path.exists() or not path.is_file():
        return None

    lines = path.read_text(encoding="utf-8").splitlines()
    if start_line < 1 or end_line < start_line or end_line > len(lines):
        return None
    return "\n".join(lines[start_line - 1 : end_line])


def _linkify_file_references(text: str, result: TestRunResult) -> str:
    """Convert common file:line references into GitHub permalinks."""
    files_base = result.environment.get("FAILURE_ANALYZER_FILES_BASE", "").strip()
    if not files_base:
        return text

    def replace(match: re.Match[str]) -> str:
        start = match.start()
        if start >= 2 and text[start - 2 : start] == "](":
            return match.group(0)
        if start >= 9 and text[start - 9 : start] == "artifact:":
            return match.group(0)

        raw_path = match.group("path")
        line = match.group("line")
        end_line = match.group("end_line")
        repo_relative = resolve_repo_relative_path(raw_path, result)
        if repo_relative is None:
            return match.group(0)

        label = f"{repo_relative}:{line}"
        anchor = f"#L{line}"
        if end_line:
            label = f"{label}-{end_line}"
            anchor = f"{anchor}-L{end_line}"
        return f"[{label}]({files_base}{repo_relative}{anchor})"

    return _FILE_LINE_PATTERN.sub(replace, text)


def linkify_report_markdown(report: str, result: TestRunResult) -> str:
    """Upgrade plain file references in non-code sections to GitHub permalinks."""
    if not report.strip():
        return report

    parts = _CODE_FENCE_SPLIT_PATTERN.split(report)
    linked_parts = [
        part if part.startswith("```") else _linkify_file_references(part, result)
        for part in parts
    ]
    return "".join(linked_parts)


def linkify_artifact_references(
    markdown: str,
    artifact_url: str | None,
    *,
    artifact_dir: Path | None = None,
) -> str:
    """Convert plain artifact:path references into artifact links."""
    if not markdown.strip() or not artifact_url:
        return markdown

    excerpts: list[tuple[str, str]] = []
    seen_excerpt_keys: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        raw_path = match.group("path")
        stripped_path = raw_path.rstrip(".,;:!?")
        suffix = raw_path[len(stripped_path) :]
        line = match.group("line")
        end_line = match.group("end_line") or line
        label = f"artifact:{stripped_path}"
        if line:
            label = f"{label}:{line}"
            if end_line and end_line != line:
                label = f"{label}-{end_line}"
            if artifact_dir is not None:
                excerpt = read_artifact_excerpt(
                    artifact_dir,
                    stripped_path,
                    start_line=int(line),
                    end_line=int(end_line or line),
                )
                if excerpt is not None:
                    key = f"{stripped_path}:{line}-{end_line}"
                    if key not in seen_excerpt_keys:
                        seen_excerpt_keys.add(key)
                        excerpts.append(
                            (
                                label,
                                excerpt,
                            )
                        )
            return f"`{label}`{suffix}"
        return f"[{label}]({artifact_url}){suffix}"

    parts = _CODE_FENCE_SPLIT_PATTERN.split(markdown)
    linked_parts = [
        part if part.startswith("```") else _ARTIFACT_REF_PATTERN.sub(replace, part)
        for part in parts
    ]
    linked = "".join(linked_parts)
    if not excerpts:
        return linked

    excerpt_blocks = "\n\n".join(
        (
            "<details>\n"
            f"<summary>`{label}` excerpt</summary>\n\n"
            "```text\n"
            f"{excerpt}\n"
            "```\n"
            "</details>"
        )
        for label, excerpt in excerpts
    )
    return f"{linked.rstrip()}\n\n## Artifact Excerpts\n\n{excerpt_blocks}\n"


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
