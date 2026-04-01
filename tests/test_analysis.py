from __future__ import annotations

from datetime import datetime, timezone
import io
from pathlib import Path

import pytest

from failure_analyzer import analysis
from failure_analyzer.deepagents_conventions import DeepAgentsConventions
from failure_analyzer.models import TestRunResult


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
    assert "time-ordered output log" in analysis.ANALYSIS_SYSTEM_PROMPT
    assert "O` means stdout" in analysis.ANALYSIS_SYSTEM_PROMPT
    assert "FAILURE_ANALYZER_FILES_BASE" in analysis.ANALYSIS_SYSTEM_PROMPT
    assert "do not invent file URLs" in analysis.ANALYSIS_SYSTEM_PROMPT
    assert "FAILURE_ANALYZER_CAN_READ_ACTIONS=true" in analysis.ANALYSIS_SYSTEM_PROMPT
    assert "gh" in analysis.ANALYSIS_SYSTEM_PROMPT


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
        "- The failure comes from pricing/pricing.go:17 and pricing/pricing_test.go:55.\n"
        "- Absolute path: /repo/examples/go-ci-demo/pricing/pricing.go:23.\n"
        "```text\npricing/pricing.go:17\n```\n"
    )

    linked = linkify_report_markdown(report, result)

    assert "[examples/go-ci-demo/pricing/pricing.go:17](https://github.com/example/repo/blob/abc123/examples/go-ci-demo/pricing/pricing.go#L17)" in linked
    assert "[examples/go-ci-demo/pricing/pricing_test.go:55](https://github.com/example/repo/blob/abc123/examples/go-ci-demo/pricing/pricing_test.go#L55)" in linked
    assert "[examples/go-ci-demo/pricing/pricing.go:23](https://github.com/example/repo/blob/abc123/examples/go-ci-demo/pricing/pricing.go#L23)" in linked
    assert "```text\npricing/pricing.go:17\n```" in linked


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
    assert analysis.resolve_model(None) == "openai:gpt-5.4-mini"


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
    assert analysis.resolve_model(None) == "openai:gpt-5.4-mini"


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
    assert analysis.resolve_model(None) == "openai:gpt-5.4-mini"


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

    class FakeAgent:
        async def astream(self, *_args, **_kwargs):
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
            yield (
                "messages",
                (
                    type(
                        "FakeChunk",
                        (),
                        {"content": [{"type": "text", "text": "## Summary\nFailure report"}]},
                    )(),
                    {},
                ),
            )
            yield (
                "values",
                {
                    "messages": [
                        {"content": "## Summary\nFailure report"},
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
        model="openai:gpt-5",
        max_output_bytes=1024,
        enable_shell_analysis=False,
        status_sink=sink,
    )
    assert result.report_markdown == "## Summary\nFailure report"
    assert result.was_streamed is True
    stderr_output = sink.getvalue()
    assert "[analyzer] Starting failure analysis..." in stderr_output
    assert "[analyzer] Tool: read_file /repo/pricing.go" in stderr_output
    assert "## Summary\nFailure report" in stderr_output
    assert captured_kwargs["memory"] == ["/repo/.deepagents/AGENTS.md"]
    assert captured_kwargs["skills"] == ["/repo/.deepagents/skills"]
    assert captured_kwargs["name"] == "failure-analyzer"
