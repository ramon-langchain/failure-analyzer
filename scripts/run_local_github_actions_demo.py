#!/usr/bin/env python3
"""Run the example Go demo under a local GitHub Actions-like environment."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Any
from pathlib import Path
from urllib.parse import quote


DEFAULT_COMMAND = (
    'set -o pipefail && mkdir -p "$FAILURE_ANALYZER_OUTPUT_DIR" && '
    'go test -json -race -cover -timeout 10s ./... '
    '| tee "$FAILURE_ANALYZER_OUTPUT_DIR/go-test.json"'
)
DEFAULT_WORKDIR = "examples/go-ci-demo"
DEFAULT_FLAGS = "nopreserveexitcode"


def run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def detect_actions_read_access(repo: str, env: dict[str, str]) -> bool:
    if shutil.which("gh") is None:
        return False
    auth = run(["gh", "auth", "status"], cwd=Path.cwd(), env=env)
    if auth.returncode != 0:
        return False
    probe = run(["gh", "api", f"repos/{repo}/actions/runs?per_page=1"], cwd=Path.cwd(), env=env)
    return probe.returncode == 0


def build_invocation_context(
    *,
    outfile: Path,
    repo_root: Path,
    repository: str,
    server_url: str,
    command: str,
    working_directory: str,
    can_read_actions: bool,
    can_comment_pr: bool,
    env: dict[str, str],
) -> None:
    def gh_json(path: str) -> dict[str, object] | None:
        result = run(["gh", "api", path], cwd=repo_root, env=env)
        if result.returncode != 0:
            return None
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def string_field(mapping: dict[str, Any], key: str) -> str:
        value = mapping.get(key)
        return value if isinstance(value, str) else ("" if value is None else str(value))

    runtime = [
        "<github_actions_runtime_context>",
        "- running_in_github_actions: true",
        f"- repository: {repository}",
        "- workflow: Local Example Go CI Demo",
        f"- workflow_ref: {repository}/.github/workflows/example-go-ci-demo.yml@refs/heads/local",
        f"- workflow_sha: {env['GITHUB_WORKFLOW_SHA']}",
        "- job: demo",
        "- event_name: workflow_dispatch",
        f"- actor: {env['GITHUB_ACTOR']}",
        f"- triggering_actor: {env['GITHUB_TRIGGERING_ACTOR']}",
        f"- ref: {env['GITHUB_REF']}",
        f"- ref_name: {env['GITHUB_REF_NAME']}",
        f"- sha: {env['GITHUB_SHA']}",
        f"- run_id: {env['GITHUB_RUN_ID']}",
        f"- run_number: {env['GITHUB_RUN_NUMBER']}",
        f"- run_attempt: {env['GITHUB_RUN_ATTEMPT']}",
        f"- run_url: {env['FAILURE_ANALYZER_RUN_URL']}",
        f"- runner_os: {env['RUNNER_OS']}",
        f"- runner_arch: {env['RUNNER_ARCH']}",
        f"- working_directory: {working_directory}",
        f"- wrapped_command: {command}",
        f"- can_read_actions_history: {'true' if can_read_actions else 'false'}",
        f"- can_comment_on_pr: {'true' if can_comment_pr else 'false'}",
        "</github_actions_runtime_context>",
    ]
    sections = ["\n".join(runtime)]

    if can_read_actions:
        runs = gh_json(f"repos/{repository}/actions/runs?event=pull_request&status=completed&per_page=20")
        if runs is not None:
            workflow_runs = runs.get("workflow_runs", [])
            if isinstance(workflow_runs, list):
                failures: list[str] = []
                for entry in workflow_runs:
                    if not isinstance(entry, dict):
                        continue
                    entry_map = dict(entry)
                    conclusion = string_field(entry_map, "conclusion")
                    if conclusion not in {"failure", "timed_out", "startup_failure", "action_required"}:
                        continue
                    failures.append(
                        "- run: {url} | workflow={name} | status={status} | head_branch={branch} | created_at={created}".format(
                            url=string_field(entry_map, "html_url"),
                            name=string_field(entry_map, "name"),
                            status=conclusion,
                            branch=string_field(entry_map, "head_branch"),
                            created=string_field(entry_map, "created_at"),
                        )
                    )
                lines = [
                    "<previous_pull_request_failures>",
                    f"- count: {len(failures)}",
                    *failures[:8],
                    "</previous_pull_request_failures>",
                ]
                sections.append("\n".join(lines))

    outfile.parent.mkdir(parents=True, exist_ok=True)
    outfile.write_text("\n\n".join(sections) + "\n", encoding="utf-8")


def parse_github_output(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run failure-analyzer locally with a GitHub Actions-like environment.",
    )
    parser.add_argument(
        "--command",
        default=DEFAULT_COMMAND,
        help=f"Wrapped test command. Default: {DEFAULT_COMMAND!r}",
    )
    parser.add_argument(
        "--working-directory",
        default=DEFAULT_WORKDIR,
        help=f"Working directory for the wrapped command. Default: {DEFAULT_WORKDIR!r}",
    )
    parser.add_argument(
        "--flags",
        default=DEFAULT_FLAGS,
        help=f"FAILURE_ANALYZER_FLAGS value. Default: {DEFAULT_FLAGS!r}",
    )
    parsed = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    work_dir = (repo_root / parsed.working_directory).resolve()
    if not work_dir.is_dir():
        raise SystemExit(f"Working directory does not exist: {work_dir}")

    sha = run(["git", "rev-parse", "HEAD"], cwd=repo_root, env=os.environ.copy(), check=True).stdout.strip()
    branch = run(
        ["git", "branch", "--show-current"],
        cwd=repo_root,
        env=os.environ.copy(),
        check=True,
    ).stdout.strip() or "main"

    temp_root = Path(tempfile.mkdtemp(prefix="failure-analyzer-local-gha-")).resolve()
    runner_temp = temp_root / "runner-temp"
    github_output = temp_root / "github-output.txt"
    github_summary = temp_root / "step-summary.md"
    context_file = runner_temp / "failure-analyzer" / "invocation-context.md"

    repository = os.environ.get("GITHUB_REPOSITORY", "ramon-langchain/failure-analyzer")
    server_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    run_url = f"{server_url}/{repository}/actions/runs/{quote(run_id, safe='')}"

    env = os.environ.copy()
    env.update(
        {
            "GITHUB_ACTIONS": "true",
            "GITHUB_REPOSITORY": repository,
            "GITHUB_SERVER_URL": server_url,
            "GITHUB_ACTOR": os.environ.get("GITHUB_ACTOR", os.environ.get("USER", "local-user")),
            "GITHUB_TRIGGERING_ACTOR": os.environ.get(
                "GITHUB_TRIGGERING_ACTOR",
                os.environ.get("USER", "local-user"),
            ),
            "GITHUB_REF": os.environ.get("GITHUB_REF", f"refs/heads/{branch}"),
            "GITHUB_REF_NAME": os.environ.get("GITHUB_REF_NAME", branch),
            "GITHUB_SHA": sha,
            "GITHUB_RUN_ID": run_id,
            "GITHUB_RUN_NUMBER": os.environ.get("GITHUB_RUN_NUMBER", "1"),
            "GITHUB_RUN_ATTEMPT": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
            "GITHUB_WORKFLOW": "Local Example Go CI Demo",
            "GITHUB_WORKFLOW_REF": f"{repository}/.github/workflows/example-go-ci-demo.yml@refs/heads/{branch}",
            "GITHUB_WORKFLOW_SHA": sha,
            "GITHUB_WORKSPACE": str(repo_root),
            "RUNNER_OS": os.environ.get("RUNNER_OS", os.uname().sysname),
            "RUNNER_ARCH": os.environ.get("RUNNER_ARCH", os.uname().machine),
            "RUNNER_TEMP": str(runner_temp),
            "GITHUB_OUTPUT": str(github_output),
            "GITHUB_STEP_SUMMARY": str(github_summary),
            "FAILURE_ANALYZER_COMMAND": parsed.command,
            "FAILURE_ANALYZER_DEFER_SUMMARY": "true",
            "FAILURE_ANALYZER_FLAGS": parsed.flags,
            "FAILURE_ANALYZER_FILES_BASE": f"{server_url}/{repository}/blob/{sha}/",
            "FAILURE_ANALYZER_OUTPUT_DIR": str(runner_temp / "failure-analyzer" / "artifacts"),
            "FAILURE_ANALYZER_RUN_URL": run_url,
            "FAILURE_ANALYZER_CONTEXT_FILE": str(context_file),
        }
    )

    can_read_actions = detect_actions_read_access(repository, env)
    env["FAILURE_ANALYZER_CAN_READ_ACTIONS"] = "true" if can_read_actions else "false"
    env["FAILURE_ANALYZER_CAN_COMMENT_PR"] = "false"
    env["FAILURE_ANALYZER_PR_NUMBER"] = ""

    build_invocation_context(
        outfile=context_file,
        repo_root=repo_root,
        repository=repository,
        server_url=server_url,
        command=parsed.command,
        working_directory=parsed.working_directory,
        can_read_actions=can_read_actions,
        can_comment_pr=False,
        env=env,
    )

    cmd = [
        "uv",
        "run",
        "failure-analyzer",
        "-C",
        parsed.working_directory,
        "--",
        "bash",
        "-lc",
        parsed.command,
    ]
    print(f"[local-gha] temp root: {temp_root}", file=sys.stderr)
    print(f"[local-gha] running: {' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(cmd, cwd=repo_root, env=env, text=True)

    output_values = parse_github_output(github_output)
    report_value = output_values.get("failure_analyzer_report_path", "")
    artifact_value = output_values.get("failure_analyzer_artifact_dir", "")
    report_path = Path(report_value).resolve() if report_value else None
    artifact_dir = Path(artifact_value).resolve() if artifact_value else None

    sys.path.insert(0, str(repo_root / "src"))
    from failure_analyzer.github_actions import append_step_summary
    from failure_analyzer.prompting import linkify_artifact_references

    if report_path is not None and report_path.exists():
        report_text = report_path.read_text(encoding="utf-8")
        report_text = linkify_artifact_references(
            report_text,
            artifact_url=None,
            artifact_dir=artifact_dir,
        )
        report_path.write_text(report_text, encoding="utf-8")
        append_step_summary(report_text)
    elif github_summary.parent.exists():
        github_summary.parent.mkdir(parents=True, exist_ok=True)

    print()
    print(
        f"Summary markdown: {github_summary if github_summary.exists() else '<not written>'}"
    )
    print(
        f"Report markdown: {report_path if report_path is not None and report_path.exists() else '<not written>'}"
    )
    print(
        f"Artifacts directory: {artifact_dir if artifact_dir is not None and artifact_dir.exists() else '<not written>'}"
    )
    print(f"GitHub-style output file: {github_output}")
    print(f"Invocation context file: {context_file}")
    print(f"Analyzer process exit code: {result.returncode}")
    if report_path is not None and report_path.exists():
        print("\nReport preview:")
        print(report_path.read_text(encoding="utf-8")[:1000].rstrip())

    print(f"\nTemp root retained at: {temp_root}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
