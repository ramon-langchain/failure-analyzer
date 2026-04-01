"""Click entrypoint for failure-analyzer."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import click
from dotenv import load_dotenv

from failure_analyzer.analysis import (
    analyze_failure,
    build_fallback_report,
    generate_pr_comment,
    SUPPORTED_SECRET_NAMES,
)
from failure_analyzer.github_actions import (
    append_step_summary,
    default_artifact_dir,
    default_report_path,
    default_pr_comment_path,
    export_artifact_dir,
    export_report_path,
    export_pr_comment_path,
    is_github_actions,
    should_defer_step_summary,
)
from failure_analyzer.prompting import (
    append_run_context,
    build_missing_credentials_summary,
    build_run_context_markdown,
    has_any_provider_credentials,
    linkify_artifact_references,
    linkify_report_markdown,
)
from failure_analyzer.runner import run_test_command


FLAGS_ENV_VAR = "FAILURE_ANALYZER_FLAGS"
NO_PRESERVE_EXIT_FLAG = "nopreserveexitcode"


def parse_flags(raw_flags: str | None) -> set[str]:
    """Parse the internal comma-separated flag env var."""
    if not raw_flags:
        return set()
    return {
        flag.strip().lower()
        for chunk in raw_flags.split(",")
        for flag in [chunk]
        if flag.strip()
    }


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
    parsed_flags = parse_flags(os.environ.get(FLAGS_ENV_VAR))
    result = await run_test_command(command, cwd=work_dir)
    if result.exit_code == 0:
        return 0

    missing_credentials_summary = None
    brief_pr_comment = ""
    if is_github_actions() and not has_any_provider_credentials(SUPPORTED_SECRET_NAMES):
        missing_credentials_summary = build_missing_credentials_summary(SUPPORTED_SECRET_NAMES)

    was_streamed = False
    if missing_credentials_summary is None:
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
    else:
        report = missing_credentials_summary
        if verbose:
            click.echo(
                "Analyzer skipped: no supported provider credentials were configured. "
                "Writing setup instructions to the GitHub Actions summary.",
                err=True,
            )

    run_context_markdown = ""
    artifact_dir = default_artifact_dir()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    if missing_credentials_summary is None:
        report = linkify_report_markdown(report, result)
        if (
            is_github_actions()
            and os.environ.get("FAILURE_ANALYZER_CAN_COMMENT_PR", "").lower() == "true"
            and os.environ.get("FAILURE_ANALYZER_PR_NUMBER", "").strip()
            and os.environ.get("FAILURE_ANALYZER_RUN_URL", "").strip()
        ):
            try:
                brief_pr_comment = await generate_pr_comment(
                    report_markdown=report,
                    command=result.command,
                    repo_root=work_dir,
                    model=model,
                    run_url=os.environ["FAILURE_ANALYZER_RUN_URL"],
                )
            except Exception as exc:
                if verbose:
                    click.echo(f"PR comment generation failed: {type(exc).__name__}: {exc}", err=True)
        report = append_run_context(report, result)
        run_context_markdown = build_run_context_markdown(result)

    github_report_handled = False
    if is_github_actions():
        export_artifact_dir(artifact_dir)
        if report_file is None and missing_credentials_summary is None:
            report_file = default_report_path()
        if report_file is not None:
            report_file.parent.mkdir(parents=True, exist_ok=True)
            report_file.write_text(report, encoding="utf-8")
            github_report_handled = True

        pr_comment_file = None
        pr_comment_exported = False
        if brief_pr_comment:
            link = os.environ.get("FAILURE_ANALYZER_RUN_URL", "").strip()
            comment_text = f"{brief_pr_comment} Full analysis: {link}" if link else brief_pr_comment
            pr_comment_file = default_pr_comment_path()
            pr_comment_file.parent.mkdir(parents=True, exist_ok=True)
            pr_comment_file.write_text(comment_text, encoding="utf-8")
            pr_comment_exported = export_pr_comment_path(pr_comment_file)

        exported = export_report_path(report_file) if report_file is not None else False
        summarized = False if should_defer_step_summary() else append_step_summary(report)
        if verbose:
            if exported:
                click.echo(
                    f"GitHub Actions report output set: failure_analyzer_report_path={report_file}",
                    err=True,
                )
            if report_file is not None:
                click.echo(f"GitHub Actions report file: {report_file}", err=True)
            if pr_comment_exported and pr_comment_file is not None:
                click.echo(f"GitHub Actions PR comment file: {pr_comment_file}", err=True)
            if summarized:
                click.echo("GitHub Actions step summary updated.", err=True)

    if not was_streamed and missing_credentials_summary is None:
        click.echo("", err=True)
        click.echo(report, err=True)
    elif was_streamed and run_context_markdown:
        click.echo("", err=True)
        click.echo(run_context_markdown, err=True)

    if report_file is not None and not github_report_handled:
        report_file.parent.mkdir(parents=True, exist_ok=True)
        report_file.write_text(report, encoding="utf-8")

    if NO_PRESERVE_EXIT_FLAG in parsed_flags:
        click.echo(
            f"[failure-analyzer] Wrapped command exited with {result.exit_code}; returning 0 because "
            f"{FLAGS_ENV_VAR} includes {NO_PRESERVE_EXIT_FLAG}.",
            err=True,
        )
        return 0

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
        raise click.UsageError("Provide the wrapped test command after failure-analyzer.")

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
