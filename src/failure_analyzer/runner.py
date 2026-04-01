"""Async subprocess execution helpers."""

from __future__ import annotations

import asyncio
import codecs
import io
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from failure_analyzer.models import TestRunResult


async def _read_stream(
    stream: asyncio.StreamReader | None,
    sink: TextIO,
) -> str:
    """Read a subprocess stream, tee it to a text sink, and return the content."""
    if stream is None:
        return ""

    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    chunks: list[str] = []

    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        text = decoder.decode(chunk)
        if text:
            sink.write(text)
            sink.flush()
            chunks.append(text)

    tail = decoder.decode(b"", final=True)
    if tail:
        sink.write(tail)
        sink.flush()
        chunks.append(tail)

    return "".join(chunks)


async def run_test_command(
    command: Sequence[str],
    *,
    cwd: Path,
    stdout_sink: TextIO | None = None,
    stderr_sink: TextIO | None = None,
) -> TestRunResult:
    """Run a test command asynchronously while streaming and capturing output."""
    if not command:
        msg = "command must not be empty"
        raise ValueError(msg)

    stdout_sink = stdout_sink or sys.stdout
    stderr_sink = stderr_sink or sys.stderr
    started_at = datetime.now(timezone.utc)

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        message = f"Command not found: {command[0]}\n"
        stderr_sink.write(message)
        stderr_sink.flush()
        finished_at = datetime.now(timezone.utc)
        return TestRunResult(
            command=tuple(command),
            cwd=cwd,
            exit_code=127,
            stdout="",
            stderr=message,
            started_at=started_at,
            finished_at=finished_at,
        )

    stdout_task = asyncio.create_task(_read_stream(process.stdout, stdout_sink))
    stderr_task = asyncio.create_task(_read_stream(process.stderr, stderr_sink))

    stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
    return_code = await process.wait()
    finished_at = datetime.now(timezone.utc)

    return TestRunResult(
        command=tuple(command),
        cwd=cwd,
        exit_code=return_code,
        stdout=stdout,
        stderr=stderr,
        started_at=started_at,
        finished_at=finished_at,
    )


def buffer_sink() -> TextIO:
    """Return an in-memory sink for tests."""
    return io.StringIO()
