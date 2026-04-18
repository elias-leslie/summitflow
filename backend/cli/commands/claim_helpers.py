"""Helper functions for claim command."""

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
    "CHERRY_PICK_HEAD",
    "BISECT_LOG",
)
_IN_PROGRESS_DIRS = (
    "rebase-merge",
    "rebase-apply",
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
        for marker_dir in _IN_PROGRESS_DIRS:
            if (git_dir / marker_dir).exists():
                hazards.append("rebase in progress")
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
            "Claim will proceed on the current checkout."
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


def _resume_via_branch(task_id: str) -> dict[str, Any]:
    """Resume a task by checking out its branch."""
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
    return {"task_id": task_id, "action": "resumed", "branch": task_branch}


def handle_existing_checkpoint(task_id: str, existing: dict[str, Any]) -> dict[str, Any]:
    """Prompt user about an existing checkpoint and either resume or abort."""
    age_str = _format_age(str(existing["created_at"]))
    typer.echo(f"Existing checkpoint found for {task_id} (created {age_str} ago).")
    return _resume_via_branch(task_id)


def print_resumed(task_id: str, result: dict[str, Any]) -> None:
    """Print output for a resumed task."""
    output_success(f"Task {task_id} resumed. Branch: {result['branch']}")


def print_claimed(task_id: str, result: dict[str, Any]) -> None:
    """Print output for a newly claimed task."""
    output_success(f"Task {task_id} claimed. Checkpoint created.")
    typer.echo(f"  Branch: {result['branch']}")
