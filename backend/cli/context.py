"""Active task context management for CLI.

Stores the current working task ID to reduce CLI friction.
Commands can use get_active_task_id() to auto-fill task_id when not provided.

Storage priority (read):
1. Explicit argument (handled by command)
2. ST_CURRENT_TASK_ID environment variable
3. Local file: .summitflow/context.json (project-local)
4. Global file: ~/.summitflow/context.json (user-global)

Storage location (write):
- Project-local if in a git repo, else user-global.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class ActiveContext:
    """Active task context data."""

    task_id: str
    set_at: str  # ISO 8601 timestamp
    project_id: str | None = None


def _get_git_root() -> Path | None:
    """Get the root of the current git repository, if any."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _get_local_context_path() -> Path | None:
    """Get the project-local context file path (.summitflow/context.json)."""
    git_root = _get_git_root()
    if git_root:
        return git_root / ".summitflow" / "context.json"
    return None


def _get_global_context_path() -> Path:
    """Get the user-global context file path (~/.summitflow/context.json)."""
    return Path.home() / ".summitflow" / "context.json"


def _read_context_file(path: Path) -> ActiveContext | None:
    """Read context from a JSON file."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return ActiveContext(
            task_id=data["task_id"],
            set_at=data.get("set_at", ""),
            project_id=data.get("project_id"),
        )
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def _write_context_file(path: Path, context: ActiveContext) -> None:
    """Write context to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "task_id": context.task_id,
        "set_at": context.set_at,
    }
    if context.project_id:
        data["project_id"] = context.project_id
    path.write_text(json.dumps(data, indent=2) + "\n")


def get_active_task_id() -> str | None:
    """Get the active task ID from environment or context file.

    Priority:
    1. ST_CURRENT_TASK_ID environment variable
    2. Local context file (.summitflow/context.json)
    3. Global context file (~/.summitflow/context.json)

    Returns:
        Task ID string, or None if no active context.
    """
    # 1. Environment variable
    env_task = os.getenv("ST_CURRENT_TASK_ID")
    if env_task:
        return env_task

    # 2. Local context file
    local_path = _get_local_context_path()
    if local_path:
        ctx = _read_context_file(local_path)
        if ctx:
            return ctx.task_id

    # 3. Global context file
    global_path = _get_global_context_path()
    ctx = _read_context_file(global_path)
    if ctx:
        return ctx.task_id

    return None


def get_active_context() -> ActiveContext | None:
    """Get full active context (task_id, set_at, project_id).

    Same priority as get_active_task_id().

    Returns:
        ActiveContext object, or None if no active context.
    """
    # 1. Environment variable (limited context)
    env_task = os.getenv("ST_CURRENT_TASK_ID")
    if env_task:
        return ActiveContext(task_id=env_task, set_at="")

    # 2. Local context file
    local_path = _get_local_context_path()
    if local_path:
        ctx = _read_context_file(local_path)
        if ctx:
            return ctx

    # 3. Global context file
    global_path = _get_global_context_path()
    return _read_context_file(global_path)


def set_active_task_id(task_id: str, project_id: str | None = None) -> Path:
    """Set the active task ID in context file.

    Writes to:
    - Local .summitflow/context.json if in a git repo
    - Global ~/.summitflow/context.json otherwise

    Returns:
        Path to the context file written.
    """
    context = ActiveContext(
        task_id=task_id,
        set_at=datetime.now(UTC).isoformat(),
        project_id=project_id,
    )

    # Prefer local context file if in a git repo
    local_path = _get_local_context_path()
    if local_path:
        _write_context_file(local_path, context)
        return local_path

    # Fall back to global context file
    global_path = _get_global_context_path()
    _write_context_file(global_path, context)
    return global_path


def clear_active_task_id() -> bool:
    """Clear the active task context.

    Removes context from both local and global files.

    Returns:
        True if any context was cleared, False if none existed.
    """
    cleared = False

    # Clear local context
    local_path = _get_local_context_path()
    if local_path and local_path.exists():
        local_path.unlink()
        cleared = True

    # Clear global context
    global_path = _get_global_context_path()
    if global_path.exists():
        global_path.unlink()
        cleared = True

    return cleared


def require_task_id(explicit_task_id: str | None) -> str:
    """Get task_id from argument or active context, or raise error.

    Use this in commands that need a task_id but want to support
    active context fallback.

    Args:
        explicit_task_id: Task ID passed as argument (takes priority)

    Returns:
        Task ID from argument or active context

    Raises:
        typer.Exit: If no task_id available
    """
    import typer

    from .output import output_error

    if explicit_task_id:
        return explicit_task_id

    active_task = get_active_task_id()
    if active_task:
        return active_task

    output_error(
        "No task specified and no active context.\n"
        "Either provide a task_id or use -t/--task flag."
    )
    raise typer.Exit(1)
