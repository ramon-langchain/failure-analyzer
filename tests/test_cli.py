from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from test_analyzer.cli import cli
from test_analyzer.github_actions import REPORT_OUTPUT_NAME
from test_analyzer.models import AnalysisResult, TestRunResult


def make_result(exit_code: int = 1) -> TestRunResult:
    from datetime import datetime, timezone

    return TestRunResult(
        command=("go", "test", "./..."),
        cwd=Path("/repo"),
        exit_code=exit_code,
        stdout="stdout text\n",
        stderr="stderr text\n",
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )


def test_cli_skips_analysis_for_success(monkeypatch) -> None:
    async def fake_run_test_command(*args, **kwargs):
        return make_result(exit_code=0)

    async def fake_analyze_failure(*args, **kwargs):
        raise AssertionError("analysis should not run")

    monkeypatch.setattr("test_analyzer.cli.run_test_command", fake_run_test_command)
    monkeypatch.setattr("test_analyzer.cli.analyze_failure", fake_analyze_failure)

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

    monkeypatch.setattr("test_analyzer.cli.run_test_command", fake_run_test_command)
    monkeypatch.setattr("test_analyzer.cli.analyze_failure", fake_analyze_failure)

    report_file = tmp_path / "report.md"
    runner = CliRunner()
    result = runner.invoke(cli, ["--report-file", str(report_file), "go", "test", "./..."])
    assert result.exit_code == 7
    assert "## Summary\nreport body" in result.output
    assert report_file.read_text(encoding="utf-8") == "## Summary\nreport body"


def test_cli_accepts_dash_c_for_working_directory(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    async def fake_run_test_command(command, *, cwd, **kwargs):
        captured["command"] = command
        captured["cwd"] = cwd
        return make_result(exit_code=0)

    monkeypatch.setattr("test_analyzer.cli.run_test_command", fake_run_test_command)

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

    monkeypatch.setattr("test_analyzer.cli.run_test_command", fake_run_test_command)
    monkeypatch.setattr("test_analyzer.cli.analyze_failure", fake_analyze_failure)

    runner = CliRunner()
    result = runner.invoke(cli, ["--verbose", "go", "test", "./..."])
    assert result.exit_code == 2
    assert "Analyzer failed: RuntimeError: boom" in result.output
    assert "fallback report" in result.output.lower()


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
    report_file = tmp_path / "runner-temp" / "test-analyzer" / "failure-analysis.md"

    monkeypatch.setattr("test_analyzer.cli.run_test_command", fake_run_test_command)
    monkeypatch.setattr("test_analyzer.cli.analyze_failure", fake_analyze_failure)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "runner-temp"))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))

    runner = CliRunner()
    result = runner.invoke(cli, ["--verbose", "go", "test", "./..."])
    assert result.exit_code == 9
    assert report_file.read_text(encoding="utf-8") == "## Summary\nreport body"
    assert f"{REPORT_OUTPUT_NAME}={report_file}" in output_file.read_text(encoding="utf-8")
    summary_text = summary_file.read_text(encoding="utf-8")
    assert "## test-analyzer Report" in summary_text
    assert "## Summary\nreport body" in summary_text
