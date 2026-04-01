from __future__ import annotations

from pathlib import Path

import pytest

from failure_analyzer.runner import buffer_sink, run_test_command


@pytest.mark.asyncio
async def test_run_test_command_captures_stdout_and_stderr() -> None:
    stdout_sink = buffer_sink()
    stderr_sink = buffer_sink()

    result = await run_test_command(
        (
            "python3",
            "-c",
            "import sys; print('hello'); sys.stderr.write('oops\\n'); raise SystemExit(3)",
        ),
        cwd=Path.cwd(),
        stdout_sink=stdout_sink,
        stderr_sink=stderr_sink,
    )

    assert result.exit_code == 3
    assert result.stdout == "hello\n"
    assert result.stderr == "oops\n"
    assert stdout_sink.getvalue() == "hello\n"
    assert stderr_sink.getvalue() == "oops\n"


@pytest.mark.asyncio
async def test_run_test_command_returns_127_for_missing_binary() -> None:
    stderr_sink = buffer_sink()

    result = await run_test_command(
        ("definitely-not-a-real-command",),
        cwd=Path.cwd(),
        stderr_sink=stderr_sink,
    )

    assert result.exit_code == 127
    assert "Command not found" in result.stderr
    assert "definitely-not-a-real-command" in stderr_sink.getvalue()
