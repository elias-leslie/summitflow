"""Helper functions for claim command.

Internal helpers split out to keep claim.py under 150 lines.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from ..output import output_error, output_success, output_warning

_UNMERGED_PREFIXES = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
_IN_PROGRESS_FILES = (
    "MERGE_HEAD",
    "REBASE_HEAD",
    "CHERRY_PICK_HEAD",
    "BISECT_LOG",
)


def is_subtask_id(id_str: str) -> bool:
    """Check if the ID looks like a subtask (e.g., 1.1, 2.3)."""
    if "." not in id_str:
        return False
    parts = id_str.split(".")
    return len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit()


def _git_status_lines() -> list[str]:
    """Return porcelain status lines, or an empty list on git failure."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        )
        return [line for line in result.stdout.splitlines() if line.strip()]
    except subprocess.CalledProcessError:
        return []


def _find_claim_hazards() -> list[str]:
    """Return concrete hazards that should block st claim."""
    hazards: list[str] = []
    for line in _git_status_lines():
        status_code = line[:2]
        if status_code in _UNMERGED_PREFIXES:
            hazards.append("unresolved merge conflicts")
            break

    git_dir = Path(".git")
    if git_dir.is_dir():
        for marker in _IN_PROGRESS_FILES:
            if (git_dir / marker).exists():
                readable = marker.lower().replace("_head", "").replace("_", " ")
                hazards.append(f"{readable} in progress")
    return list(dict.fromkeys(hazards))


def require_claim_safe_tree() -> None:
    """Block claim only when the working tree is hazardous, not merely dirty."""
    hazards = _find_claim_hazards()
    if hazards:
        output_error(
            "Working tree is not safe for st claim.\n"
            f"Resolve first: {', '.join(hazards)}"
        )
        raise typer.Exit(1)
    if _git_status_lines():
        output_warning(
            "Working tree has uncommitted changes, but no claim-blocking hazards were found. "
            "Proceeding with checkpoint baseline capture."
        )


def require_clean_tree() -> None:
    """Backward-compatible alias for older claim command imports."""
    require_claim_safe_tree()


def _format_age(created_at: str) -> str:
    """Return human-readable age string from ISO timestamp."""
    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    age = datetime.now(UTC) - created
    hours = int(age.total_seconds() / 3600)
    mins = int((age.total_seconds() % 3600) / 60)
    return f"{hours}h {mins}m" if hours > 0 else f"{mins}m"


def _resume_from_worktree(task_id: str, existing: dict[str, Any]) -> dict[str, Any]:
    """Resume a task that already has a live worktree."""
    return {
        "task_id": task_id,
        "action": "resumed",
        "branch": f"{task_id}/main",
        "worktree_path": existing.get("worktree_path"),
        "backend_port": existing.get("backend_port"),
        "frontend_port": existing.get("frontend_port"),
    }


def _resume_via_branch(task_id: str, worktree_path: str | None) -> dict[str, Any]:
    """Resume a task by checking out its branch (legacy / missing worktree)."""
    task_branch = f"{task_id}/main"
    try:
        subprocess.run(
            ["git", "checkout", task_branch],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        output_error(f"Failed to checkout branch: {e.stderr}")
        raise typer.Exit(1) from None
    return {"task_id": task_id, "action": "resumed", "branch": task_branch, "worktree_path": worktree_path}


def handle_existing_checkpoint(task_id: str, existing: dict[str, Any]) -> dict[str, Any]:
    """Prompt user about an existing checkpoint and either resume or abort."""
    age_str = _format_age(str(existing["created_at"]))
    typer.echo(f"Existing checkpoint found for {task_id} (created {age_str} ago).")
    typer.echo(f"Size: {existing.get('size', 'unknown')}")
    if existing.get("worktree_path"):
        typer.echo(f"Worktree: {existing['worktree_path']}")
    worktree_path = existing.get("worktree_path")
    if worktree_path and existing.get("worktree_exists") == "true":
        return _resume_from_worktree(task_id, existing)
    return _resume_via_branch(task_id, worktree_path)


def print_worktree_info(task_id: str, result: dict[str, Any]) -> None:
    """Print worktree path and optional isolated-service instructions."""
    typer.echo(f"  Worktree: {result['worktree_path']}")
    typer.echo("\nTo work in isolation:")
    typer.echo(f"  cd {result['worktree_path']}")
    if result.get("backend_port") and result.get("frontend_port"):
        typer.echo("\nTo start isolated services:")
        typer.echo(f"  worktree-services.sh start {task_id}")
        typer.echo(f"  Backend:  http://localhost:{result['backend_port']}")
        typer.echo(f"  Frontend: http://localhost:{result['frontend_port']}")


def print_resumed(task_id: str, result: dict[str, Any]) -> None:
    """Print output for a resumed task."""
    output_success(f"Task {task_id} resumed. Branch: {result['branch']}")
    if result.get("worktree_path"):
        print_worktree_info(task_id, result)


def print_claimed(task_id: str, result: dict[str, Any]) -> None:
    """Print output for a newly claimed task."""
    output_success(f"Task {task_id} claimed. Checkpoint created.")
    typer.echo(f"  Branch: {result['branch']}")
    if result.get("worktree_path"):
        print_worktree_info(task_id, result)
