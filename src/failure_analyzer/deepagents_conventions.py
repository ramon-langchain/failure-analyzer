"""Deep Agents-compatible memory and skills discovery."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

AGENT_NAME_ENV_VAR = "FAILURE_ANALYZER_AGENT_NAME"
DISABLE_GLOBAL_SKILLS_ENV_VAR = "FAILURE_ANALYZER_DISABLE_GLOBAL_SKILLS"
DEFAULT_AGENT_NAME = "failure-analyzer"
_VALID_AGENT_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\s]+$")


@dataclass(frozen=True, slots=True)
class DeepAgentsConventions:
    """Resolved Deep Agents memory and skills sources."""

    user_cwd: Path
    project_root: Path
    agent_name: str
    memory_sources: list[str]
    skill_sources: list[str]


def resolve_agent_name(agent_name: str | None = None) -> str:
    """Resolve the Deep Agents agent name used for user-level memory and skills."""
    candidate = (agent_name or os.environ.get(AGENT_NAME_ENV_VAR) or DEFAULT_AGENT_NAME).strip()
    if not candidate or not _VALID_AGENT_NAME_PATTERN.fullmatch(candidate):
        return DEFAULT_AGENT_NAME
    return candidate


def find_project_root(start_path: str | Path | None = None) -> Path | None:
    """Find the nearest parent directory containing `.git`."""
    current = Path(start_path or Path.cwd()).expanduser().resolve()
    for parent in [current, *list(current.parents)]:
        if (parent / ".git").exists():
            return parent
    return None


def discover_memory_sources(
    project_root: Path,
    *,
    agent_name: str,
    home_dir: Path | None = None,
) -> list[str]:
    """Discover Deep Agents memory files in CLI-compatible order."""
    home = (home_dir or Path.home()).expanduser().resolve()
    candidates = [
        home / ".deepagents" / agent_name / "AGENTS.md",
        project_root / ".deepagents" / "AGENTS.md",
        project_root / "AGENTS.md",
    ]
    return [str(path) for path in candidates if path.exists()]


def discover_skill_sources(
    project_root: Path,
    *,
    agent_name: str,
    home_dir: Path | None = None,
) -> list[str]:
    """Discover Deep Agents skill directories in CLI-compatible precedence order."""
    home = (home_dir or Path.home()).expanduser().resolve()
    disable_global_skills = os.environ.get(DISABLE_GLOBAL_SKILLS_ENV_VAR, "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    candidates: list[Path] = []
    if not disable_global_skills:
        candidates.extend(
            [
                home / ".deepagents" / agent_name / "skills",
                home / ".agents" / "skills",
            ]
        )
    candidates.extend(
        [
            project_root / ".deepagents" / "skills",
            project_root / ".agents" / "skills",
        ]
    )
    if not disable_global_skills:
        candidates.append(home / ".claude" / "skills")
    candidates.append(project_root / ".claude" / "skills")
    return [str(path) for path in candidates if path.exists() and path.is_dir()]


def load_deepagents_conventions(
    user_cwd: str | Path,
    *,
    agent_name: str | None = None,
    home_dir: Path | None = None,
) -> DeepAgentsConventions:
    """Resolve project root plus Deep Agents memory and skills sources."""
    resolved_cwd = Path(user_cwd).expanduser().resolve()
    project_root = find_project_root(resolved_cwd) or resolved_cwd
    resolved_agent_name = resolve_agent_name(agent_name)
    return DeepAgentsConventions(
        user_cwd=resolved_cwd,
        project_root=project_root,
        agent_name=resolved_agent_name,
        memory_sources=discover_memory_sources(
            project_root,
            agent_name=resolved_agent_name,
            home_dir=home_dir,
        ),
        skill_sources=discover_skill_sources(
            project_root,
            agent_name=resolved_agent_name,
            home_dir=home_dir,
        ),
    )
