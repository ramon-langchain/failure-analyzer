"""Click entrypoint for test-analyzer."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
from dotenv import load_dotenv

from test_analyzer.analysis import analyze_failure, build_fallback_report
from test_analyzer.github_actions import (
    append_step_summary,
    default_report_path,
    export_report_path,
    is_github_actions,
)
from test_analyzer.runner import run_test_command


async def _async_main(
    *,
    command: tuple[str, ...],
    model: str | None,
    work_dir: Path,
    report_file: Path | None,
    max_output_bytes: int,
    enable_shell_analysis: bool,
    verbose: bool,
) -> int:
    """Run the wrapped test command and invoke analysis on failures."""
    result = await run_test_command(command, cwd=work_dir)
    if result.exit_code == 0:
        return 0

    was_streamed = False
    try:
        analysis = await analyze_failure(
            result,
            repo_root=work_dir,
            model=model,
            max_output_bytes=max_output_bytes,
            enable_shell_analysis=enable_shell_analysis,
        )
        report = analysis.report_markdown
        was_streamed = analysis.was_streamed
        if analysis.used_truncation and verbose:
            click.echo("Analyzer input was truncated to respect --max-output-bytes.", err=True)
    except Exception as exc:
        if verbose:
            click.echo(f"Analyzer failed: {type(exc).__name__}: {exc}", err=True)
        report = build_fallback_report(result, exc)

    github_report_handled = False
    if is_github_actions():
        if report_file is None:
            report_file = default_report_path()
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(report, encoding="utf-8")
        github_report_handled = True

        exported = export_report_path(report_file)
        summarized = append_step_summary(report)
        if verbose:
            if exported:
                click.echo(
                    f"GitHub Actions report output set: test_analyzer_report_path={report_file}",
                    err=True,
                )
            click.echo(f"GitHub Actions report file: {report_file}", err=True)
            if summarized:
                click.echo("GitHub Actions step summary updated.", err=True)

    if not was_streamed:
        click.echo("", err=True)
        click.echo(report, err=True)

    if report_file is not None and not github_report_handled:
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(report, encoding="utf-8")

    return result.exit_code


@click.command(
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
    }
)
@click.option("--model", metavar="TEXT", help="LLM identifier, for example openai:gpt-5.")
@click.option(
    "-C",
    type=click.Path(path_type=Path, file_okay=False, resolve_path=True),
    default=Path.cwd,
    show_default="current working directory",
    help="Working directory for the wrapped command and the analyzer.",
)
@click.option(
    "--report-file",
    type=click.Path(path_type=Path, dir_okay=False, resolve_path=True),
    help="Optional Markdown file path for saving the failure report.",
)
@click.option(
    "--max-output-bytes",
    type=click.IntRange(min=1024),
    default=120_000,
    show_default=True,
    help="Maximum bytes of captured output included in analyzer prompts.",
)
@click.option(
    "--no-shell-analysis",
    is_flag=True,
    help="Disable shell-based diagnostics and limit the analyzer to file inspection.",
)
@click.option("--verbose", is_flag=True, help="Print analyzer diagnostics.")
@click.argument("command", nargs=-1, type=click.UNPROCESSED)
def cli(
    model: str | None,
    c: Path,
    report_file: Path | None,
    max_output_bytes: int,
    no_shell_analysis: bool,
    verbose: bool,
    command: tuple[str, ...],
) -> None:
    """Run a test command and analyze failures with a Deep Agent."""
    if not command:
        raise click.UsageError("Provide the wrapped test command after test-analyzer.")

    exit_code = asyncio.run(
        _async_main(
            command=command,
            model=model,
            work_dir=c,
            report_file=report_file,
            max_output_bytes=max_output_bytes,
            enable_shell_analysis=not no_shell_analysis,
            verbose=verbose,
        )
    )
    if exit_code:
        raise click.exceptions.Exit(exit_code)


def main() -> None:
    """Console script entrypoint."""
    load_dotenv()
    cli()
