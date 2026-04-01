"""Failure-analysis service powered by LangChain Deep Agents."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from textwrap import dedent
from typing import IO, Any, cast

from langchain_openai import ChatOpenAI

from failure_analyzer.context_builder import append_invocation_context, load_invocation_context
from failure_analyzer.deepagents_conventions import load_deepagents_conventions
from failure_analyzer.models import AnalysisRequest, AnalysisResult, TestRunResult
from failure_analyzer.prompting import (
    STREAM_FORMAT_LEGEND,
    append_custom_instructions,
    format_environment_block,
    format_exact_command,
    format_timestamp,
    load_pr_comment_prompt,
    load_system_prompt,
)
from failure_analyzer.report_validation import (
    degrade_invalid_markdown,
    detect_unlinked_symbols,
    format_symbol_link_feedback,
    format_validation_feedback,
    validate_report_markdown,
)

DEFAULT_MODEL = "openai:gpt-5.4-mini"
MODEL_ENV_VAR = "FAILURE_ANALYZER_MODEL"
THINKING_EFFORT_ENV_VAR = "FAILURE_ANALYZER_THINKING_EFFORT"
DEFAULT_THINKING_EFFORT = "medium"
DEFAULT_OPENAI_MODEL = "openai:gpt-5.4-mini"
DEFAULT_ANTHROPIC_MODEL = "anthropic:claude-sonnet-4-6"
DEFAULT_GOOGLE_MODEL = "google_genai:gemini-3.1-flash-lite-preview"
DEFAULT_VERTEX_MODEL = "google_vertexai:gemini-3.1-flash-lite-preview"
OPENAI_SECRET_NAMES = (
    "FAILURE_ANALYZER_OPENAI_API_KEY",
    "OPENAI_API_KEY",
)
ANTHROPIC_SECRET_NAMES = (
    "FAILURE_ANALYZER_ANTHROPIC_API_KEY",
    "ANTHROPIC_API_KEY",
)
GOOGLE_SECRET_NAMES = (
    "FAILURE_ANALYZER_GOOGLE_API_KEY",
    "GOOGLE_API_KEY",
)
VERTEX_SECRET_NAMES = (
    "FAILURE_ANALYZER_GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_PROJECT",
)
SUPPORTED_SECRET_NAMES = (
    *OPENAI_SECRET_NAMES,
    *ANTHROPIC_SECRET_NAMES,
    *GOOGLE_SECRET_NAMES,
    *VERTEX_SECRET_NAMES,
)

ANALYSIS_SYSTEM_PROMPT = load_system_prompt()
PR_COMMENT_SYSTEM_PROMPT = load_pr_comment_prompt()


def resolve_model(model: str | None) -> str:
    """Resolve the configured model with CLI and environment precedence."""
    if model:
        return model
    configured = os.environ.get(MODEL_ENV_VAR)
    if configured:
        return configured

    if _get_env("OPENAI_API_KEY"):
        return DEFAULT_OPENAI_MODEL
    if _get_env("ANTHROPIC_API_KEY"):
        return DEFAULT_ANTHROPIC_MODEL
    if _get_env("GOOGLE_API_KEY"):
        return DEFAULT_GOOGLE_MODEL
    if _get_env("GOOGLE_CLOUD_PROJECT"):
        return DEFAULT_VERTEX_MODEL

    return DEFAULT_MODEL


def resolve_thinking_effort(thinking_effort: str | None) -> str:
    """Resolve the configured OpenAI thinking effort."""
    configured = thinking_effort or os.environ.get(THINKING_EFFORT_ENV_VAR)
    if configured:
        return configured
    return DEFAULT_THINKING_EFFORT


def build_agent_model(model: str | None, *, thinking_effort: str | None) -> str | ChatOpenAI:
    """Build the model object passed into Deep Agents."""
    resolved = resolve_model(model)
    if resolved.startswith("openai:"):
        openai_model = cast(Any, ChatOpenAI)
        return openai_model(
            model=resolved.partition(":")[2],
            use_responses_api=True,
            reasoning_effort=resolve_thinking_effort(thinking_effort),
        )
    return resolved


def build_analysis_system_prompt(custom_instructions: str | None) -> str:
    """Build the final analysis system prompt including runtime invocation context."""
    with_context = append_invocation_context(ANALYSIS_SYSTEM_PROMPT, load_invocation_context())
    return append_custom_instructions(with_context, custom_instructions)


def _get_env(name: str) -> str | None:
    """Read prefixed failure-analyzer env vars before the default provider vars."""
    return os.environ.get(f"FAILURE_ANALYZER_{name}") or os.environ.get(name)


def truncate_text(text: str, *, max_bytes: int) -> tuple[str, bool]:
    """Truncate long text by preserving the head and tail."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False

    marker = "\n\n... output truncated ...\n\n"
    marker_bytes = marker.encode("utf-8")
    if len(marker_bytes) >= max_bytes:
        return marker[:max_bytes], True

    remaining = max_bytes - len(marker_bytes)
    head_size = remaining // 2
    tail_size = remaining - head_size

    head = encoded[:head_size].decode("utf-8", errors="ignore")
    tail = encoded[-tail_size:].decode("utf-8", errors="ignore")
    return f"{head}{marker}{tail}", True


def build_analysis_request(
    result: TestRunResult,
    *,
    repo_root: Path,
    max_output_bytes: int,
    enable_shell_analysis: bool,
    allow_rerun: bool,
    thinking_effort: str = DEFAULT_THINKING_EFFORT,
    timed_output_artifact_ref: str | None = None,
) -> AnalysisRequest:
    """Transform a failed test run into an analysis request."""
    combined_output, _ = truncate_text(result.combined_output, max_bytes=max_output_bytes)
    if timed_output_artifact_ref is None and result.timed_output_path is not None:
        timed_output_artifact_ref = "timed-output.log"
    return AnalysisRequest(
        command=result.command,
        repo_root=repo_root,
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        combined_output=combined_output,
        environment=result.environment,
        started_at=result.started_at,
        finished_at=result.finished_at,
        timed_output_path=result.timed_output_path,
        timed_output_artifact_ref=timed_output_artifact_ref,
        max_output_bytes=max_output_bytes,
        enable_shell_analysis=enable_shell_analysis,
        allow_rerun=allow_rerun,
        thinking_effort=thinking_effort,
    )


def render_user_prompt(request: AnalysisRequest) -> tuple[str, bool]:
    """Create the analyzer prompt with bounded command output."""
    stdout_text, stdout_truncated = truncate_text(request.stdout, max_bytes=request.max_output_bytes)
    stderr_text, stderr_truncated = truncate_text(request.stderr, max_bytes=request.max_output_bytes)
    combined_text, combined_truncated = truncate_text(
        request.combined_output,
        max_bytes=request.max_output_bytes,
    )

    shell_mode = "enabled" if request.enable_shell_analysis else "disabled"
    duration_ms = (
        int((request.finished_at - request.started_at).total_seconds() * 1000)
        if request.started_at is not None and request.finished_at is not None
        else None
    )
    duration_text = f"{duration_ms} ms" if duration_ms is not None else "<unknown>"
    timed_output_path = request.timed_output_path or Path("<not captured>")
    timed_output_artifact_line = (
        f"- Timed output log fence format: ```logs {request.timed_output_artifact_ref}:<start>-<end>\n"
        if request.timed_output_artifact_ref
        else ""
    )
    rerun_guidance = (
        "- You may rerun the test command or a narrowed variant if that would materially improve the diagnosis.\n"
        "- Any rerun must use short timeouts and should aim to finish within about two minutes total.\n"
        "- Prefer targeted reruns over broad expensive reruns.\n"
        if request.allow_rerun
        else "- Do not rerun the test command. Diagnose from the existing output and repository state only.\n"
    )
    environment_block = format_environment_block(request.environment)
    prompt = dedent(
        f"""\
        Analyze this failed test run.

        - Working directory: `{request.repo_root}`
        - Exact command: `{format_exact_command(list(request.command))}`
        - Exit code: `{request.exit_code}`
        - Started at (UTC): `{format_timestamp(request.started_at)}`
        - Finished at (UTC): `{format_timestamp(request.finished_at)}`
        - Duration: `{duration_text}`
        - Shell-based diagnostics: {shell_mode}
        - Rerunning tests permitted: {"yes" if request.allow_rerun else "no"}
        - OpenAI thinking effort: `{request.thinking_effort}`
        - Full timed output file: `{timed_output_path}`
        - Timed output format: {STREAM_FORMAT_LEGEND}
        {timed_output_artifact_line}

        The exit code is the ground truth. Explain why the test failed. You may inspect files outside the working directory if they are relevant and accessible on the host.

        {rerun_guidance}

        ### Environment (redacted)

        ```text
        {environment_block}
        ```

        ### Output Preview

        ```text
        {combined_text}
        ```

        ### Raw STDOUT

        ```text
        {stdout_text or "<empty>"}
        ```

        ### Raw STDERR

        ```text
        {stderr_text or "<empty>"}
        ```
        """
    )
    return prompt, stdout_truncated or stderr_truncated or combined_truncated


def render_report_generation_prompt(request: AnalysisRequest, report_path: Path) -> tuple[str, bool]:
    """Create the analyzer prompt and instruct the agent to write a report file."""
    prompt, used_truncation = render_user_prompt(request)
    output_contract = dedent(
        f"""\

        ### Report Output Contract

        Write your final report to this exact file path in GitHub-flavored Markdown:

        ```text
        {report_path}
        ```

        The file you write is the source of truth. Do not rely on the chat response as the final output.
        """
    )
    return f"{prompt.rstrip()}\n{output_contract}", used_truncation


def extract_text_content(message: Any) -> str:
    """Extract text content from a LangChain message-like object."""
    if isinstance(message, dict) and "content" in message:
        content = message["content"]
    else:
        content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(part for part in parts if part)
    return str(content)


def extract_chunk_text(chunk: Any) -> str:
    """Extract incremental text from a streamed LLM chunk."""
    content = getattr(chunk, "content", chunk)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "".join(parts)
    return ""


def format_tool_call(tool_call: dict[str, Any]) -> str:
    """Summarize a tool call for stderr progress output."""
    name = str(tool_call.get("name", "unknown"))
    args = tool_call.get("args", {})
    if not isinstance(args, dict):
        return name

    for key in ("command", "file_path", "path", "query", "description"):
        value = args.get(key)
        if value:
            text = str(value).replace("\n", " ")
            return f"{name} {text[:120]}"

    if args:
        preview = ", ".join(f"{key}={value!r}" for key, value in list(args.items())[:2])
        return f"{name} {preview[:120]}"
    return name


def find_last_text_message(messages: list[Any]) -> str:
    """Return the last message with extractable text content."""
    for message in reversed(messages):
        text = extract_text_content(message).strip()
        if text:
            return text
    return ""


def emit_status_line(status_sink: IO[str], message: str) -> None:
    """Write a single analyzer status line to stderr."""
    status_sink.write(f"[analyzer] {message}\n")
    status_sink.flush()


def summarize_tool_result(content: Any) -> str:
    """Return a compact first-line/last-line summary of tool output."""
    text = extract_text_content(content).strip()
    if not text:
        return "<empty>"

    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return "<empty>"
    if len(lines) == 1:
        return lines[0][:160]

    first = lines[0][:120]
    last = lines[-1][:120]
    return f"{first} ... {last}"


def emit_new_message_statuses(
    messages: list[Any],
    *,
    seen_messages: int,
    seen_tool_call_ids: set[str],
    status_sink: IO[str],
) -> int:
    """Emit status lines for newly appended streamed messages."""
    for message in messages[seen_messages:]:
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            for tool_call in tool_calls:
                tool_call_id = str(tool_call.get("id", ""))
                if tool_call_id and tool_call_id in seen_tool_call_ids:
                    continue
                if tool_call_id:
                    seen_tool_call_ids.add(tool_call_id)
                emit_status_line(status_sink, f"Tool: {format_tool_call(tool_call)}")
            continue

        if hasattr(message, "tool_call_id"):
            name = getattr(message, "name", "tool")
            summary = summarize_tool_result(getattr(message, "content", ""))
            emit_status_line(status_sink, f"Tool finished: {name} -> {summary}")
            emit_status_line(status_sink, "Thinking...")

    return len(messages)


def build_fallback_report(result: TestRunResult, exc: Exception) -> str:
    """Return a minimal Markdown report if agent analysis fails."""
    stderr_excerpt, _ = truncate_text(result.stderr or result.stdout, max_bytes=8_000)
    return dedent(
        f"""\
        ## Summary
        The wrapped test command failed, and the analysis agent also failed before producing a report.

        ## Root Cause
        Analyzer error: `{type(exc).__name__}: {exc}`

        ## Evidence
        - Command: `{" ".join(result.command)}`
        - Exit code: `{result.exit_code}`

        ```text
        {stderr_excerpt or "<no captured output>"}
        ```

        ## Likely Fix Direction
        Re-run with `--verbose` to inspect the analyzer failure, then address the underlying test error from the captured output above.

        ## Confidence
        Low. This is a fallback report because the analyzer itself failed.
        """
    )


def read_output_file(path: Path) -> str:
    """Read an agent-authored output file."""
    if not path.exists():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8").strip()


def format_missing_output_feedback(path: Path) -> str:
    """Build a detailed prompt when the agent failed to produce its output file."""
    parent_listing = []
    if path.parent.exists():
        parent_listing = sorted(child.name for child in path.parent.iterdir())
    listing_text = "\n".join(f"- {name}" for name in parent_listing) or "<empty directory>"
    return dedent(
        f"""\
        The required output file was not produced or is empty.

        Required file path:
        ```text
        {path}
        ```

        Parent directory contents right now:
        ```text
        {listing_text}
        ```

        Fix this by writing the full final GitHub-flavored Markdown report to the exact required file path above.
        Do not rely on the chat response. Re-read the path carefully and create or overwrite that exact file.
        """
    ).strip()


async def stream_agent_status(
    agent: Any,
    *,
    prompt: str,
    status_sink: IO[str],
) -> None:
    """Run an agent request while surfacing tool activity to stderr."""
    seen_messages = 0
    seen_tool_call_ids: set[str] = set()
    async for mode, data in agent.astream(
        {"messages": [{"role": "user", "content": prompt}]},
        stream_mode=["values"],
    ):
        if mode != "values":
            continue
        messages = data.get("messages", [])
        if isinstance(messages, list):
            seen_messages = emit_new_message_statuses(
                messages,
                seen_messages=seen_messages,
                seen_tool_call_ids=seen_tool_call_ids,
                status_sink=status_sink,
            )


async def analyze_failure(
    result: TestRunResult,
    *,
    repo_root: Path,
    report_path: Path,
    artifact_dir: Path,
    model: str | None,
    custom_instructions: str | None,
    max_output_bytes: int,
    enable_shell_analysis: bool,
    allow_rerun: bool,
    thinking_effort: str | None = None,
    status_sink: IO[str] | None = None,
) -> AnalysisResult:
    """Run the Deep Agent and return its validated Markdown analysis."""
    from deepagents import create_deep_agent
    from deepagents.backends import FilesystemBackend, LocalShellBackend

    status_sink = status_sink or sys.stderr
    conventions = load_deepagents_conventions(repo_root)

    request = build_analysis_request(
        result,
        repo_root=repo_root,
        max_output_bytes=max_output_bytes,
        enable_shell_analysis=enable_shell_analysis,
        allow_rerun=allow_rerun,
        thinking_effort=resolve_thinking_effort(thinking_effort),
        timed_output_artifact_ref=(
            "timed-output.log"
            if result.timed_output_path is not None
            else None
        ),
    )
    if result.timed_output_path is not None and result.timed_output_path.exists():
        artifact_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(result.timed_output_path, artifact_dir / "timed-output.log")
    user_prompt, used_truncation = render_report_generation_prompt(request, report_path)

    backend: Any
    if enable_shell_analysis:
        backend = LocalShellBackend(
            root_dir=repo_root,
            virtual_mode=False,
            inherit_env=True,
        )
    else:
        backend = FilesystemBackend(
            root_dir=repo_root,
            virtual_mode=False,
        )

    agent = create_deep_agent(
        model=build_agent_model(model, thinking_effort=thinking_effort),
        tools=[],
        system_prompt=build_analysis_system_prompt(custom_instructions),
        backend=backend,
        memory=conventions.memory_sources or None,
        skills=conventions.skill_sources or None,
        name=conventions.agent_name,
    )
    emit_status_line(status_sink, "Starting failure analysis...")
    emit_status_line(status_sink, "Thinking...")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    await stream_agent_status(agent, prompt=user_prompt, status_sink=status_sink)

    try:
        report = read_output_file(report_path)
    except (FileNotFoundError, OSError):
        emit_status_line(
            status_sink,
            "Report file was missing or empty after the initial pass; requesting a focused recovery attempt.",
        )
        emit_status_line(status_sink, "Thinking...")
        await stream_agent_status(
            agent,
            prompt=format_missing_output_feedback(report_path),
            status_sink=status_sink,
        )
        report = read_output_file(report_path)
    validation = validate_report_markdown(report, result=result, artifact_dir=artifact_dir)
    attempts = 0
    while not validation.is_valid and attempts < 2:
        attempts += 1
        emit_status_line(
            status_sink,
            f"Report validation failed ({len(validation.issues)} issue(s)); requesting repair attempt {attempts}/2.",
        )
        emit_status_line(status_sink, "Thinking...")
        repair_prompt = format_validation_feedback(validation, report_path)
        await stream_agent_status(agent, prompt=repair_prompt, status_sink=status_sink)
        try:
            report = read_output_file(report_path)
        except (FileNotFoundError, OSError):
            emit_status_line(
                status_sink,
                "Report file was missing or empty after a repair attempt; requesting a focused recovery attempt.",
            )
            emit_status_line(status_sink, "Thinking...")
            await stream_agent_status(
                agent,
                prompt=format_missing_output_feedback(report_path),
                status_sink=status_sink,
            )
            report = read_output_file(report_path)
        validation = validate_report_markdown(report, result=result, artifact_dir=artifact_dir)

    if validation.is_valid:
        symbol_reminder = detect_unlinked_symbols(report)
        if symbol_reminder.needed:
            emit_status_line(
                status_sink,
                f"Report may have {len(symbol_reminder.symbols)} symbol reference(s) without defining locations; requesting one optional cleanup pass.",
            )
            emit_status_line(status_sink, "Thinking...")
            symbol_prompt = format_symbol_link_feedback(symbol_reminder, report_path)
            await stream_agent_status(agent, prompt=symbol_prompt, status_sink=status_sink)
            try:
                report = read_output_file(report_path)
            except (FileNotFoundError, OSError):
                emit_status_line(
                    status_sink,
                    "Report file was missing or empty after the symbol-link reminder; requesting a focused recovery attempt.",
                )
                emit_status_line(status_sink, "Thinking...")
                await stream_agent_status(
                    agent,
                    prompt=format_missing_output_feedback(report_path),
                    status_sink=status_sink,
                )
                report = read_output_file(report_path)
            validation = validate_report_markdown(report, result=result, artifact_dir=artifact_dir)

    if not validation.is_valid:
        emit_status_line(
            status_sink,
            f"Report still has {len(validation.issues)} invalid reference(s) after repair; downgrading them to plain text.",
        )
        report = degrade_invalid_markdown(report, validation)
        report_path.write_text(report, encoding="utf-8")

    status_sink.write("\n")
    status_sink.write(report)
    if not report.endswith("\n"):
        status_sink.write("\n")
    status_sink.flush()

    return AnalysisResult(
        report_markdown=report,
        report_path=report_path,
        used_truncation=used_truncation,
        was_streamed=True,
    )


async def generate_pr_comment(
    *,
    report_markdown: str,
    command: tuple[str, ...],
    repo_root: Path,
    comment_path: Path,
    model: str | None,
    custom_instructions: str | None,
    thinking_effort: str | None = None,
    run_url: str,
    status_sink: IO[str] | None = None,
) -> str:
    """Generate a brief PR comment from the main analysis report."""
    from deepagents import create_deep_agent
    from deepagents.backends import FilesystemBackend

    status_sink = status_sink or sys.stderr
    conventions = load_deepagents_conventions(repo_root)
    backend = FilesystemBackend(root_dir=repo_root, virtual_mode=False)
    agent = create_deep_agent(
        model=build_agent_model(model, thinking_effort=thinking_effort),
        tools=[],
        system_prompt=append_custom_instructions(PR_COMMENT_SYSTEM_PROMPT, custom_instructions),
        backend=backend,
        memory=conventions.memory_sources or None,
        skills=conventions.skill_sources or None,
        name=f"{conventions.agent_name}-pr-comment",
    )
    prompt = dedent(
        f"""\
        Exact test command: `{format_exact_command(list(command))}`
        Workflow run URL: `{run_url}`
        Write the final PR comment to this exact file path:

        ```text
        {comment_path}
        ```

        Full failure analysis report:

        {report_markdown}
        """
    )
    emit_status_line(status_sink, "Generating short PR comment...")
    comment_path.parent.mkdir(parents=True, exist_ok=True)
    await stream_agent_status(agent, prompt=prompt, status_sink=status_sink)
    comment = read_output_file(comment_path)
    return " ".join(comment.split())
