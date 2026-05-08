"""Build kwargs dict for Agent Hub complete calls."""

from __future__ import annotations

import subprocess
from typing import Any


def _detect_git_branch(project_path: str) -> str | None:
    """Detect current git branch from project path."""
    try:
        result = subprocess.run(
            ["git", "-C", project_path, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def build_complete_kwargs(
    prompt: str,
    agent_slug: str,
    project_path: str,
    project_id: str,
    task_id: str,
    session_id: str,
    max_turns: int | None = None,
    include_roles: list[str] | None = None,
) -> dict[str, Any]:
    """Build kwargs dict for Agent Hub complete call."""
    current_branch = _detect_git_branch(project_path)
    kwargs: dict[str, Any] = {
        "messages": [{"role": "user", "content": prompt}],
        "agent_slug": agent_slug,
        "external_id": task_id,
        "working_dir": project_path,
        "execute_tools": True,
        "project_id": project_id,
        "use_memory": True,
        "memory_group_id": f"project:{project_id}",
        "trace_id": task_id,
        "include_roles": include_roles or [],
        "session_id": session_id,
    }
    if max_turns and max_turns > 1:
        kwargs["max_turns"] = max_turns
    if current_branch:
        kwargs["current_branch"] = current_branch
    return kwargs
