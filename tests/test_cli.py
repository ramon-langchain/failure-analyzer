from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from failure_analyzer.cli import cli
from failure_analyzer.github_actions import REPORT_OUTPUT_NAME
from failure_analyzer.models import AnalysisResult, TestRunResult


def make_result(exit_code: int = 1) -> TestRunResult:
    from datetime import datetime, timezone

    return TestRunResult(
        command=("go", "test", "./..."),
        cwd=Path("/repo"),
        exit_code=exit_code,
        stdout="stdout text\n",
        stderr="stderr text\n",
        started_at=datetime(2026, 4, 1, 7, 0, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 4, 1, 7, 0, 2, 500000, tzinfo=timezone.utc),
        environment={
            "CI": "true",
            "OPENAI_API_KEY": "secret",
            "PATH": "/usr/bin:/bin",
        },
        timed_output_path=Path("/repo/.failure-analyzer/timed-output.log"),
    )


def test_cli_skips_analysis_for_success(monkeypatch) -> None:
    async def fake_run_test_command(*args, **kwargs):
        return make_result(exit_code=0)

    async def fake_analyze_failure(*args, **kwargs):
        raise AssertionError("analysis should not run")

    monkeypatch.setattr("failure_analyzer.cli.run_test_command", fake_run_test_command)
    monkeypatch.setattr("failure_analyzer.cli.analyze_failure", fake_analyze_failure)

    runner = CliRunner()
    result = runner.invoke(cli, ["go", "test", "./..."])
    assert result.exit_code == 0
    assert result.output == ""


def test_cli_runs_analysis_and_preserves_exit_code(monkeypatch, tmp_path: Path) -> None:
    async def fake_run_test_command(*args, **kwargs):
        return make_result(exit_code=7)

    async def fake_analyze_failure(*args, **kwargs):
        return AnalysisResult(
            report_markdown="## Summary\nreport body",
            used_truncation=False,
            was_streamed=False,
        )

    monkeypatch.setattr("failure_analyzer.cli.run_test_command", fake_run_test_command)
    monkeypatch.setattr("failure_analyzer.cli.analyze_failure", fake_analyze_failure)

    report_file = tmp_path / "report.md"
    runner = CliRunner()
    result = runner.invoke(cli, ["--report-file", str(report_file), "go", "test", "./..."])
    assert result.exit_code == 7
    assert "## Summary\nreport body" in result.output
    report_text = report_file.read_text(encoding="utf-8")
    assert "## Summary\nreport body" in report_text
    assert "## Run Context" in report_text
    assert "`OPENAI_API_KEY=<redacted>`" not in report_text
    assert "OPENAI_API_KEY=<redacted>" in report_text
    assert "Duration: `2500 ms`" in report_text


def test_cli_accepts_dash_c_for_working_directory(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    async def fake_run_test_command(command, *, cwd, **kwargs):
        captured["command"] = command
        captured["cwd"] = cwd
        return make_result(exit_code=0)

    monkeypatch.setattr("failure_analyzer.cli.run_test_command", fake_run_test_command)

    runner = CliRunner()
    result = runner.invoke(cli, ["-C", str(tmp_path), "go", "test", "./..."])
    assert result.exit_code == 0
    assert captured["command"] == ("go", "test", "./...")
    assert captured["cwd"] == tmp_path


def test_cli_emits_fallback_report_when_analysis_fails(monkeypatch) -> None:
    async def fake_run_test_command(*args, **kwargs):
        return make_result(exit_code=2)

    async def fake_analyze_failure(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("failure_analyzer.cli.run_test_command", fake_run_test_command)
    monkeypatch.setattr("failure_analyzer.cli.analyze_failure", fake_analyze_failure)

    runner = CliRunner()
    result = runner.invoke(cli, ["--verbose", "go", "test", "./..."])
    assert result.exit_code == 2
    assert "Analyzer failed: RuntimeError: boom" in result.output
    assert "fallback report" in result.output.lower()
    assert "## Run Context" in result.output


def test_cli_writes_github_actions_report_and_outputs_path(monkeypatch, tmp_path: Path) -> None:
    async def fake_run_test_command(*args, **kwargs):
        return make_result(exit_code=9)

    async def fake_analyze_failure(*args, **kwargs):
        return AnalysisResult(
            report_markdown="## Summary\nreport body",
            used_truncation=False,
            was_streamed=False,
        )

    output_file = tmp_path / "github_output.txt"
    summary_file = tmp_path / "step_summary.md"
    report_file = tmp_path / "runner-temp" / "failure-analyzer" / "failure-analysis.md"

    monkeypatch.setattr("failure_analyzer.cli.run_test_command", fake_run_test_command)
    monkeypatch.setattr("failure_analyzer.cli.analyze_failure", fake_analyze_failure)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "runner-temp"))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    runner = CliRunner()
    result = runner.invoke(cli, ["--verbose", "go", "test", "./..."])
    assert result.exit_code == 9
    report_text = report_file.read_text(encoding="utf-8")
    assert "## Summary\nreport body" in report_text
    assert "## Run Context" in report_text
    assert f"{REPORT_OUTPUT_NAME}={report_file}" in output_file.read_text(encoding="utf-8")
    summary_text = summary_file.read_text(encoding="utf-8")
    assert "## failure-analyzer Report" in summary_text
    assert "## Summary\nreport body" in summary_text
    assert "## Run Context" in summary_text


def test_cli_writes_missing_credentials_summary_in_github_actions(
    monkeypatch,
    tmp_path: Path,
) -> None:
    async def fake_run_test_command(*args, **kwargs):
        return make_result(exit_code=3)

    async def fake_analyze_failure(*args, **kwargs):
        raise AssertionError("analysis should be skipped when credentials are missing")

    output_file = tmp_path / "github_output.txt"
    summary_file = tmp_path / "step_summary.md"

    monkeypatch.setattr("failure_analyzer.cli.run_test_command", fake_run_test_command)
    monkeypatch.setattr("failure_analyzer.cli.analyze_failure", fake_analyze_failure)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    monkeypatch.delenv("FAILURE_ANALYZER_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

    runner = CliRunner()
    result = runner.invoke(cli, ["--verbose", "go", "test", "./..."])
    assert result.exit_code == 3
    assert "Analyzer skipped: no supported provider credentials were configured." in result.output
    assert "fallback report" not in result.output.lower()
    assert not output_file.exists()

    summary_text = summary_file.read_text(encoding="utf-8")
    assert "## failure-analyzer setup required" in summary_text
    assert "`OPENAI_API_KEY`" in summary_text
    assert "`FAILURE_ANALYZER_OPENAI_API_KEY`" in summary_text
