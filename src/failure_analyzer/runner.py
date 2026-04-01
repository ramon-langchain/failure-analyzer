"""Async subprocess execution helpers."""

from __future__ import annotations

import asyncio
import codecs
import io
import os
import sys
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from failure_analyzer.models import TestRunResult


class TimedOutputRecorder:
    """Persist a full time-ordered stdout/stderr log to disk."""

    def __init__(self, *, path: Path, started_at_ns: int) -> None:
        self.path = path
        self._started_at_ns = started_at_ns
        self._lock = asyncio.Lock()
        self._pending: dict[str, str] = {"O": "", "E": ""}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", encoding="utf-8")

    def _relative_milliseconds(self) -> int:
        return max(0, (time.perf_counter_ns() - self._started_at_ns) // 1_000_000)

    def _format_line(self, stream_char: str, line: str) -> str:
        return f"+{self._relative_milliseconds():08d}ms {stream_char} {line}\n"

    async def record_text(self, stream_char: str, text: str) -> None:
        """Record incoming text, preserving partial lines until they complete."""
        async with self._lock:
            buffered = self._pending[stream_char] + text
            lines = buffered.splitlines(keepends=True)
            trailing_fragment = ""
            if lines and not lines[-1].endswith(("\n", "\r")):
                trailing_fragment = lines.pop()

            for line in lines:
                normalized = line.rstrip("\r\n")
                self._handle.write(self._format_line(stream_char, normalized))

            self._pending[stream_char] = trailing_fragment
            self._handle.flush()

    async def finalize_stream(self, stream_char: str) -> None:
        """Flush any incomplete final line for a stream."""
        async with self._lock:
            pending = self._pending[stream_char]
            if pending:
                self._handle.write(self._format_line(stream_char, pending))
                self._pending[stream_char] = ""
                self._handle.flush()

    def close(self) -> None:
        """Close the underlying output file."""
        self._handle.close()


def default_timed_output_path(cwd: Path) -> Path:
    """Choose a stable path for the full timed output log."""
    return cwd / ".failure-analyzer" / "timed-output.log"


async def _read_stream(
    stream: asyncio.StreamReader | None,
    sink: TextIO,
    *,
    recorder: TimedOutputRecorder,
    stream_char: str,
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
            await recorder.record_text(stream_char, text)
            chunks.append(text)

    tail = decoder.decode(b"", final=True)
    if tail:
        sink.write(tail)
        sink.flush()
        await recorder.record_text(stream_char, tail)
        chunks.append(tail)

    await recorder.finalize_stream(stream_char)
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
    started_at_ns = time.perf_counter_ns()
    environment = dict(os.environ)
    timed_output_path = default_timed_output_path(cwd)
    recorder = TimedOutputRecorder(path=timed_output_path, started_at_ns=started_at_ns)

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
        await recorder.record_text("E", message)
        await recorder.finalize_stream("E")
        finished_at = datetime.now(timezone.utc)
        recorder.close()
        return TestRunResult(
            command=tuple(command),
            cwd=cwd,
            exit_code=127,
            stdout="",
            stderr=message,
            started_at=started_at,
            finished_at=finished_at,
            environment=environment,
            timed_output_path=timed_output_path,
        )

    stdout_task = asyncio.create_task(
        _read_stream(process.stdout, stdout_sink, recorder=recorder, stream_char="O")
    )
    stderr_task = asyncio.create_task(
        _read_stream(process.stderr, stderr_sink, recorder=recorder, stream_char="E")
    )

    stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
    return_code = await process.wait()
    finished_at = datetime.now(timezone.utc)
    recorder.close()

    return TestRunResult(
        command=tuple(command),
        cwd=cwd,
        exit_code=return_code,
        stdout=stdout,
        stderr=stderr,
        started_at=started_at,
        finished_at=finished_at,
        environment=environment,
        timed_output_path=timed_output_path,
    )


def buffer_sink() -> TextIO:
    """Return an in-memory sink for tests."""
    return io.StringIO()
