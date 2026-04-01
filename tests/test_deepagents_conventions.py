from __future__ import annotations

from pathlib import Path

from failure_analyzer.deepagents_conventions import (
    DEFAULT_AGENT_NAME,
    discover_memory_sources,
    discover_skill_sources,
    find_project_root,
    load_deepagents_conventions,
    resolve_agent_name,
)


def test_resolve_agent_name_defaults_and_validates(monkeypatch) -> None:
    monkeypatch.delenv("FAILURE_ANALYZER_AGENT_NAME", raising=False)
    assert resolve_agent_name() == DEFAULT_AGENT_NAME

    monkeypatch.setenv("FAILURE_ANALYZER_AGENT_NAME", "ci agent")
    assert resolve_agent_name() == "ci agent"

    monkeypatch.setenv("FAILURE_ANALYZER_AGENT_NAME", "../bad")
    assert resolve_agent_name() == DEFAULT_AGENT_NAME


def test_find_project_root_walks_up_to_git_directory(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    nested = project_root / "a" / "b"
    (project_root / ".git").mkdir(parents=True)
    nested.mkdir(parents=True)

    assert find_project_root(nested) == project_root.resolve()


def test_discovers_memory_and_skills_in_deepagents_order(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project_root = tmp_path / "project"
    agent_name = "failure-analyzer"

    user_memory = home / ".deepagents" / agent_name / "AGENTS.md"
    project_memory = project_root / ".deepagents" / "AGENTS.md"
    repo_memory = project_root / "AGENTS.md"
    for path in (user_memory, project_memory, repo_memory):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# memory\n", encoding="utf-8")

    skill_dirs = [
        home / ".deepagents" / agent_name / "skills",
        home / ".agents" / "skills",
        project_root / ".deepagents" / "skills",
        project_root / ".agents" / "skills",
        home / ".claude" / "skills",
        project_root / ".claude" / "skills",
    ]
    for path in skill_dirs:
        path.mkdir(parents=True, exist_ok=True)

    assert discover_memory_sources(project_root, agent_name=agent_name, home_dir=home) == [
        str(user_memory),
        str(project_memory),
        str(repo_memory),
    ]
    assert discover_skill_sources(project_root, agent_name=agent_name, home_dir=home) == [
        str(path) for path in skill_dirs
    ]


def test_load_deepagents_conventions_uses_project_root_for_discovery(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project_root = tmp_path / "project"
    working_dir = project_root / "subdir"
    (project_root / ".git").mkdir(parents=True)
    working_dir.mkdir(parents=True)

    memory = project_root / ".deepagents" / "AGENTS.md"
    memory.parent.mkdir(parents=True, exist_ok=True)
    memory.write_text("# project memory\n", encoding="utf-8")

    conventions = load_deepagents_conventions(working_dir, home_dir=home)

    assert conventions.user_cwd == working_dir.resolve()
    assert conventions.project_root == project_root.resolve()
    assert conventions.memory_sources == [str(memory)]
