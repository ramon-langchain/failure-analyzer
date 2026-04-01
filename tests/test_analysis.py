from __future__ import annotations

from datetime import datetime, timezone
import io
from pathlib import Path

import pytest

from failure_analyzer import analysis
from failure_analyzer.deepagents_conventions import DeepAgentsConventions
from failure_analyzer.models import TestRunResult
from failure_analyzer.report_validation import validate_report_markdown


def make_result(**overrides: object) -> TestRunResult:
    base = {
        "command": ("go", "test", "./..."),
        "cwd": Path("/repo"),
        "exit_code": 1,
        "stdout": "ok package/a\n",
        "stderr": "FAIL package/b\npanic: boom\n",
        "started_at": datetime(2026, 4, 1, 7, 0, 0, tzinfo=timezone.utc),
        "finished_at": datetime(2026, 4, 1, 7, 0, 5, tzinfo=timezone.utc),
        "environment": {
            "CI": "true",
            "OPENAI_API_KEY": "secret",
            "PATH": "/usr/bin:/bin",
            "FAILURE_ANALYZER_CAN_READ_ACTIONS": "true",
            "FAILURE_ANALYZER_FILES_BASE": "https://github.com/example/repo/blob/abc123/",
        },
        "timed_output_path": Path("/tmp/failure-analyzer/timed-output.log"),
    }
    base.update(overrides)
    return TestRunResult(**base)


def test_truncate_text_preserves_head_and_tail() -> None:
    text = "a" * 200 + "tail"
    truncated, did_truncate = analysis.truncate_text(text, max_bytes=64)
    assert did_truncate is True
    assert truncated.startswith("a")
    assert "output truncated" in truncated
    assert truncated.endswith("tail")


def test_render_user_prompt_includes_failure_context() -> None:
    request = analysis.build_analysis_request(
        make_result(),
        repo_root=Path("/repo"),
        max_output_bytes=1024,
        enable_shell_analysis=True,
    )
    prompt, used_truncation = analysis.render_user_prompt(request)
    assert used_truncation is False
    assert "go test ./..." in prompt
    assert "Exit code: `1`" in prompt
    assert "panic: boom" in prompt
    assert "/tmp/failure-analyzer/timed-output.log" in prompt
    assert "OPENAI_API_KEY=<redacted>" in prompt
    assert "Duration: `5000 ms`" in prompt


def test_system_prompt_is_loaded_from_resource_file() -> None:
    assert "<agent_identity>" in analysis.ANALYSIS_SYSTEM_PROMPT
    assert "<analysis_rules>" in analysis.ANALYSIS_SYSTEM_PROMPT
    assert "<output_contract>" in analysis.ANALYSIS_SYSTEM_PROMPT
    assert "time-ordered output log" in analysis.ANALYSIS_SYSTEM_PROMPT
    assert "O` means stdout" in analysis.ANALYSIS_SYSTEM_PROMPT
    assert "FAILURE_ANALYZER_FILES_BASE" in analysis.ANALYSIS_SYSTEM_PROMPT
    assert "do not invent file URLs" in analysis.ANALYSIS_SYSTEM_PROMPT
    assert "do not construct Markdown links yourself" in analysis.ANALYSIS_SYSTEM_PROMPT
    assert "FAILURE_ANALYZER_CAN_READ_ACTIONS=true" in analysis.ANALYSIS_SYSTEM_PROMPT
    assert "gh" in analysis.ANALYSIS_SYSTEM_PROMPT
    assert "GitHub-flavored Markdown" in analysis.ANALYSIS_SYSTEM_PROMPT
    assert "```go path/to/file.go#L55-L70" in analysis.ANALYSIS_SYSTEM_PROMPT


def test_pr_comment_prompt_is_loaded_from_resource_file() -> None:
    assert "<output_requirements>" in analysis.PR_COMMENT_SYSTEM_PROMPT
    assert "write the final comment to the exact Markdown file path" in analysis.PR_COMMENT_SYSTEM_PROMPT
    assert "exactly one paragraph" in analysis.PR_COMMENT_SYSTEM_PROMPT
    assert "Do not include a \"full analysis\" link" in analysis.PR_COMMENT_SYSTEM_PROMPT


def test_append_custom_instructions_adds_override_section() -> None:
    from failure_analyzer.prompting import append_custom_instructions

    combined = append_custom_instructions("<base>Prompt</base>", "Prefer logs over code.")
    assert "<user_override_instructions>" in combined
    assert "supersede any conflicting built-in instructions" in combined
    assert "Prefer logs over code." in combined


def test_build_run_context_markdown_collapses_full_environment(tmp_path: Path) -> None:
    from failure_analyzer.prompting import build_run_context_markdown

    timed_output_path = tmp_path / "timed-output.log"
    timed_output_path.write_text("+00000001ms O hello\n+00000002ms E boom\n", encoding="utf-8")
    markdown = build_run_context_markdown(make_result(timed_output_path=timed_output_path))
    assert "| Field | Value |" in markdown
    assert "### Important Environment (redacted)" in markdown
    assert "- `CI=true`" in markdown
    assert "- `FAILURE_ANALYZER_CAN_READ_ACTIONS=true`" in markdown
    assert "- `OPENAI_API_KEY=<redacted>`" in markdown
    assert "- `FAILURE_ANALYZER_FILES_BASE=https://github.com/example/repo/blob/abc123/`" in markdown
    assert "<summary>Timed Output Excerpt</summary>" in markdown
    assert "+00000001ms O hello" in markdown
    assert "<details>" in markdown
    assert "<summary>Full Environment (redacted)</summary>" in markdown


def test_linkify_report_markdown_rewrites_file_references() -> None:
    from failure_analyzer.prompting import linkify_report_markdown

    result = make_result(
        cwd=Path("/repo/examples/go-ci-demo"),
        environment={
            "FAILURE_ANALYZER_FILES_BASE": "https://github.com/example/repo/blob/abc123/",
            "GITHUB_WORKSPACE": "/repo",
        },
    )
    report = (
        "## Evidence\n"
        "- The failure comes from pricing/pricing.go:17 and `pricing/pricing_test.go:55`.\n"
        "- Absolute path: /repo/examples/go-ci-demo/pricing/pricing.go:23.\n"
        "- Range: pricing/pricing.go:23-36.\n"
        "```text\npricing/pricing.go:17\n```\n"
    )

    linked = linkify_report_markdown(report, result)

    assert "[examples/go-ci-demo/pricing/pricing.go:17](https://github.com/example/repo/blob/abc123/examples/go-ci-demo/pricing/pricing.go#L17)" in linked
    assert "[examples/go-ci-demo/pricing/pricing_test.go:55](https://github.com/example/repo/blob/abc123/examples/go-ci-demo/pricing/pricing_test.go#L55)" in linked
    assert "[examples/go-ci-demo/pricing/pricing.go:23](https://github.com/example/repo/blob/abc123/examples/go-ci-demo/pricing/pricing.go#L23)" in linked
    assert "[examples/go-ci-demo/pricing/pricing.go:23-36](https://github.com/example/repo/blob/abc123/examples/go-ci-demo/pricing/pricing.go#L23-L36)" in linked
    assert "```text\npricing/pricing.go:17\n```" in linked


def test_linkify_report_markdown_preserves_subproject_prefix_for_repo_relative_paths() -> None:
    from failure_analyzer.prompting import linkify_report_markdown

    result = make_result(
        cwd=Path("/repo/examples/go-ci-demo"),
        environment={
            "FAILURE_ANALYZER_FILES_BASE": "https://github.com/example/repo/blob/abc123/",
            "GITHUB_WORKSPACE": "/repo",
        },
    )
    report = "See pricing/pricing_test.go:66 and pricing/pricing.go:45.\n"

    linked = linkify_report_markdown(report, result)

    assert "[examples/go-ci-demo/pricing/pricing_test.go:66](https://github.com/example/repo/blob/abc123/examples/go-ci-demo/pricing/pricing_test.go#L66)" in linked
    assert "[examples/go-ci-demo/pricing/pricing.go:45](https://github.com/example/repo/blob/abc123/examples/go-ci-demo/pricing/pricing.go#L45)" in linked


def test_linkify_artifact_references_rewrites_plain_artifact_markers() -> None:
    from failure_analyzer.prompting import linkify_artifact_references

    markdown = (
        "See artifact:logs/failure.log and `artifact:notes/repro.md`.\n"
        "```text\nartifact:logs/raw.log\n```\n"
    )
    linked = linkify_artifact_references(
        markdown,
        "https://github.com/example/repo/actions/runs/123/artifacts/999",
    )

    assert "[artifact:logs/failure.log](https://github.com/example/repo/actions/runs/123/artifacts/999)" in linked
    assert "[artifact:notes/repro.md](https://github.com/example/repo/actions/runs/123/artifacts/999)" in linked
    assert "```text\nartifact:logs/raw.log\n```" in linked


def test_validate_report_markdown_accepts_valid_source_and_artifact_refs(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    artifact_dir = tmp_path / "artifacts"
    source_file = workspace / "pkg" / "pricing.go"
    artifact_file = artifact_dir / "logs" / "failure.log"
    source_file.parent.mkdir(parents=True)
    artifact_file.parent.mkdir(parents=True)
    source_file.write_text("package pkg\n\nfunc Tax() int {\n\treturn 91\n}\n", encoding="utf-8")
    artifact_file.write_text("boom\n", encoding="utf-8")

    result = make_result(
        cwd=workspace,
        environment={"GITHUB_WORKSPACE": str(workspace)},
    )
    markdown = (
        "See pkg/pricing.go:3-5 and artifact:logs/failure.log.\n\n"
        "```go pkg/pricing.go#L3-L5\n"
        "func Tax() int {\n\treturn 91\n}\n"
        "```\n"
    )

    validation = validate_report_markdown(markdown, result=result, artifact_dir=artifact_dir)
    assert validation.is_valid is True


def test_validate_report_markdown_rejects_bad_excerpt_and_missing_artifact(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    artifact_dir = tmp_path / "artifacts"
    source_file = workspace / "pkg" / "pricing.go"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("package pkg\n\nfunc Tax() int {\n\treturn 91\n}\n", encoding="utf-8")

    result = make_result(
        cwd=workspace,
        environment={"GITHUB_WORKSPACE": str(workspace)},
    )
    markdown = (
        "See pkg/pricing.go:99 and artifact:logs/missing.log.\n\n"
        "```go pkg/pricing.go#L3-L5\n"
        "func Tax() int {\n\treturn 90\n}\n"
        "```\n"
    )

    validation = validate_report_markdown(markdown, result=result, artifact_dir=artifact_dir)
    assert validation.is_valid is False
    reasons = [issue.reason for issue in validation.issues]
    assert any("outside file length" in reason for reason in reasons)
    assert any("artifact does not exist" in reason for reason in reasons)
    assert any("does not exactly match" in reason for reason in reasons)


def test_resolve_model_defaults_to_gpt_5_4_mini(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(analysis.MODEL_ENV_VAR, raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_GOOGLE_CLOUD_PROJECT", raising=False)
    assert analysis.resolve_model(None) == "openai:gpt-5.4"


def test_resolve_model_prefers_explicit_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(analysis.MODEL_ENV_VAR, "openai:gpt-custom")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    assert analysis.resolve_model(None) == "openai:gpt-custom"


def test_resolve_model_selects_openai_when_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(analysis.MODEL_ENV_VAR, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_GOOGLE_CLOUD_PROJECT", raising=False)
    assert analysis.resolve_model(None) == "openai:gpt-5.4"


def test_resolve_model_selects_anthropic_when_no_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(analysis.MODEL_ENV_VAR, raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_GOOGLE_CLOUD_PROJECT", raising=False)
    assert analysis.resolve_model(None) == "anthropic:claude-sonnet-4-6"


def test_resolve_model_selects_google_flash_lite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(analysis.MODEL_ENV_VAR, raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_GOOGLE_CLOUD_PROJECT", raising=False)
    assert analysis.resolve_model(None) == "google_genai:gemini-3.1-flash-lite-preview"


def test_resolve_model_selects_vertex_flash_lite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(analysis.MODEL_ENV_VAR, raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.delenv("FAILURE_ANALYZER_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_GOOGLE_CLOUD_PROJECT", raising=False)
    assert analysis.resolve_model(None) == "google_vertexai:gemini-3.1-flash-lite-preview"


def test_failure_analyzer_prefixed_openai_key_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(analysis.MODEL_ENV_VAR, raising=False)
    monkeypatch.setenv("FAILURE_ANALYZER_OPENAI_API_KEY", "prefixed")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "default-anthropic")
    monkeypatch.setenv("GOOGLE_API_KEY", "default-google")
    monkeypatch.delenv("FAILURE_ANALYZER_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_GOOGLE_CLOUD_PROJECT", raising=False)
    assert analysis.resolve_model(None) == "openai:gpt-5.4"


def test_failure_analyzer_prefixed_anthropic_key_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(analysis.MODEL_ENV_VAR, raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("FAILURE_ANALYZER_ANTHROPIC_API_KEY", "prefixed")
    monkeypatch.setenv("GOOGLE_API_KEY", "default-google")
    monkeypatch.delenv("FAILURE_ANALYZER_GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_GOOGLE_CLOUD_PROJECT", raising=False)
    assert analysis.resolve_model(None) == "anthropic:claude-sonnet-4-6"


def test_failure_analyzer_prefixed_google_key_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(analysis.MODEL_ENV_VAR, raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("FAILURE_ANALYZER_GOOGLE_API_KEY", "prefixed")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "default-project")
    monkeypatch.delenv("FAILURE_ANALYZER_GOOGLE_CLOUD_PROJECT", raising=False)
    assert analysis.resolve_model(None) == "google_genai:gemini-3.1-flash-lite-preview"


def test_failure_analyzer_prefixed_vertex_project_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(analysis.MODEL_ENV_VAR, raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FAILURE_ANALYZER_GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("FAILURE_ANALYZER_GOOGLE_CLOUD_PROJECT", "prefixed-project")
    assert analysis.resolve_model(None) == "google_vertexai:gemini-3.1-flash-lite-preview"


@pytest.mark.asyncio
async def test_analyze_failure_returns_agent_report(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_kwargs: dict[str, object] = {}
    report_path = Path("/tmp/failure-analyzer/report.md")
    artifact_dir = Path("/tmp/failure-analyzer/artifacts")

    class FakeAgent:
        async def astream(self, *_args, **_kwargs):
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text("## Summary\nFailure report", encoding="utf-8")
            yield (
                "values",
                {
                    "messages": [
                        type(
                            "FakeAIMessage",
                            (),
                            {
                                "tool_calls": [
                                    {
                                        "id": "tool-1",
                                        "name": "read_file",
                                        "args": {"file_path": "/repo/pricing.go"},
                                    }
                                ]
                            },
                        )(),
                        type(
                            "FakeToolMessage",
                            (),
                            {"tool_call_id": "tool-1", "name": "read_file", "content": "ok"},
                        )(),
                    ]
                },
            )

    class FakeFilesystemBackend:
        def __init__(self, **_: object) -> None:
            pass

    class FakeLocalShellBackend(FakeFilesystemBackend):
        pass

    def fake_create_deep_agent(**kwargs: object) -> FakeAgent:
        captured_kwargs.update(kwargs)
        return FakeAgent()

    import sys
    import types

    deepagents_module = types.SimpleNamespace(create_deep_agent=fake_create_deep_agent)
    backends_module = types.SimpleNamespace(
        FilesystemBackend=FakeFilesystemBackend,
        LocalShellBackend=FakeLocalShellBackend,
    )
    monkeypatch.setitem(sys.modules, "deepagents", deepagents_module)
    monkeypatch.setitem(sys.modules, "deepagents.backends", backends_module)
    monkeypatch.setattr(
        analysis,
        "load_deepagents_conventions",
        lambda _repo_root: DeepAgentsConventions(
            user_cwd=Path("/repo"),
            project_root=Path("/repo"),
            agent_name="failure-analyzer",
            memory_sources=["/repo/.deepagents/AGENTS.md"],
            skill_sources=["/repo/.deepagents/skills"],
        ),
    )

    sink = io.StringIO()
    result = await analysis.analyze_failure(
        make_result(),
        repo_root=Path("/repo"),
        report_path=report_path,
        artifact_dir=artifact_dir,
        model="openai:gpt-5",
        custom_instructions="Prefer precise source references.",
        max_output_bytes=1024,
        enable_shell_analysis=False,
        status_sink=sink,
    )
    assert result.report_markdown == "## Summary\nFailure report"
    assert result.report_path == report_path
    assert result.was_streamed is True
    stderr_output = sink.getvalue()
    assert "[analyzer] Starting failure analysis..." in stderr_output
    assert "[analyzer] Tool: read_file /repo/pricing.go" in stderr_output
    assert "## Summary\nFailure report" in stderr_output
    assert captured_kwargs["memory"] == ["/repo/.deepagents/AGENTS.md"]
    assert captured_kwargs["skills"] == ["/repo/.deepagents/skills"]
    assert captured_kwargs["name"] == "failure-analyzer"
    assert "Prefer precise source references." in str(captured_kwargs["system_prompt"])


@pytest.mark.asyncio
async def test_generate_pr_comment_returns_single_line_text(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_kwargs: dict[str, object] = {}
    comment_path = Path("/tmp/failure-analyzer/pr-comment.md")

    class FakeAgent:
        async def astream(self, *_args, **_kwargs):
            comment_path.parent.mkdir(parents=True, exist_ok=True)
            comment_path.write_text(
                "Root cause is bad rounding in pricing plus free-shipping threshold logic.\n",
                encoding="utf-8",
            )
            yield (
                "values",
                {
                    "messages": []
                },
            )

    class FakeFilesystemBackend:
        def __init__(self, **_: object) -> None:
            pass

    def fake_create_deep_agent(**kwargs: object) -> FakeAgent:
        captured_kwargs.update(kwargs)
        return FakeAgent()

    import sys
    import types

    deepagents_module = types.SimpleNamespace(create_deep_agent=fake_create_deep_agent)
    backends_module = types.SimpleNamespace(FilesystemBackend=FakeFilesystemBackend)
    monkeypatch.setitem(sys.modules, "deepagents", deepagents_module)
    monkeypatch.setitem(sys.modules, "deepagents.backends", backends_module)
    monkeypatch.setattr(
        analysis,
        "load_deepagents_conventions",
        lambda _repo_root: DeepAgentsConventions(
            user_cwd=Path("/repo"),
            project_root=Path("/repo"),
            agent_name="failure-analyzer",
            memory_sources=["/repo/.deepagents/AGENTS.md"],
            skill_sources=["/repo/.deepagents/skills"],
        ),
    )

    comment = await analysis.generate_pr_comment(
        report_markdown="## Summary\nfull report",
        command=("go", "test", "./..."),
        repo_root=Path("/repo"),
        comment_path=comment_path,
        model="openai:gpt-5",
        custom_instructions="Mention confidence only if low.",
        run_url="https://github.com/example/repo/actions/runs/123",
    )

    assert comment == "Root cause is bad rounding in pricing plus free-shipping threshold logic."
    assert captured_kwargs["name"] == "failure-analyzer-pr-comment"
    assert "Mention confidence only if low." in str(captured_kwargs["system_prompt"])


@pytest.mark.asyncio
async def test_analyze_failure_repairs_invalid_report(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    report_path = tmp_path / "report.md"
    artifact_dir = tmp_path / "artifacts"
    artifact_file = artifact_dir / "logs" / "failure.log"
    artifact_file.parent.mkdir(parents=True)
    artifact_file.write_text("boom\n", encoding="utf-8")
    workspace = tmp_path / "repo"
    source_file = workspace / "pkg" / "pricing.go"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("package pkg\n\nfunc Tax() int {\n\treturn 91\n}\n", encoding="utf-8")
    prompts: list[str] = []

    class FakeAgent:
        async def astream(self, payload, **_kwargs):
            prompt = payload["messages"][0]["content"]
            prompts.append(prompt)
            if "failed validation" in prompt:
                report_path.write_text(
                    "## Summary\nFixed report citing pkg/pricing.go:3-5 and artifact:logs/failure.log.\n\n"
                    "## Root Cause\nMismatch.\n\n"
                    "## Evidence\n```go pkg/pricing.go#L3-L5\nfunc Tax() int {\n\treturn 91\n}\n```\n\n"
                    "## Likely Fix Direction\nAdjust the implementation.\n\n"
                    "## Confidence\nHigh.\n",
                    encoding="utf-8",
                )
            else:
                report_path.write_text(
                    "## Summary\nBroken report citing pkg/pricing.go:99 and artifact:logs/missing.log.\n\n"
                    "## Root Cause\nMismatch.\n\n"
                    "## Evidence\n```go pkg/pricing.go#L3-L5\nfunc Tax() int {\n\treturn 90\n}\n```\n\n"
                    "## Likely Fix Direction\nAdjust the implementation.\n\n"
                    "## Confidence\nHigh.\n",
                    encoding="utf-8",
                )
            yield ("values", {"messages": []})

    class FakeFilesystemBackend:
        def __init__(self, **_: object) -> None:
            pass

    class FakeLocalShellBackend(FakeFilesystemBackend):
        pass

    def fake_create_deep_agent(**_kwargs: object) -> FakeAgent:
        return FakeAgent()

    import sys
    import types

    deepagents_module = types.SimpleNamespace(create_deep_agent=fake_create_deep_agent)
    backends_module = types.SimpleNamespace(
        FilesystemBackend=FakeFilesystemBackend,
        LocalShellBackend=FakeLocalShellBackend,
    )
    monkeypatch.setitem(sys.modules, "deepagents", deepagents_module)
    monkeypatch.setitem(sys.modules, "deepagents.backends", backends_module)
    monkeypatch.setattr(
        analysis,
        "load_deepagents_conventions",
        lambda _repo_root: DeepAgentsConventions(
            user_cwd=workspace,
            project_root=workspace,
            agent_name="failure-analyzer",
            memory_sources=[],
            skill_sources=[],
        ),
    )

    result = await analysis.analyze_failure(
        make_result(
            cwd=workspace,
            environment={"GITHUB_WORKSPACE": str(workspace), "OPENAI_API_KEY": "secret"},
        ),
        repo_root=workspace,
        report_path=report_path,
        artifact_dir=artifact_dir,
        model="openai:gpt-5",
        custom_instructions=None,
        max_output_bytes=1024,
        enable_shell_analysis=False,
        status_sink=io.StringIO(),
    )

    assert "Fixed report citing pkg/pricing.go:3-5" in result.report_markdown
    assert any("failed validation" in prompt for prompt in prompts[1:])
