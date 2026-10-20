"""Helper functions for claim command."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from ..output import output_error, output_success, output_warning
from .done_validators import is_subtask_id  # noqa: F401  # re-exported for claim.py

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


def handle_existing_checkpoint(task_id: str, existing: dict[str, Any]) -> dict[str, Any]:
    """Acknowledge existing checkpoint and resume on the current checkout."""
    age_str = _format_age(str(existing["created_at"]))
    typer.echo(f"Existing checkpoint found for {task_id} (created {age_str} ago).")
    return {"task_id": task_id, "action": "resumed"}


def _print_claim_brief(task_id: str, result: dict[str, Any]) -> None:
    """Use the already fetched task; no repeated gates or full context fetch."""
    from .done_task_scope import task_scope_paths

    task = result.get("task") or {}
    if not isinstance(task, dict):
        return
    typer.echo("Ownership: this task is claimed; preflight clear.")
    if task.get("title"):
        typer.echo(f"Task: {task['title']}")
    if task.get("description"):
        typer.echo(str(task["description"]))
    paths = sorted(task_scope_paths(task))
    if paths:
        shown = ", ".join(paths[:3])
        remaining = f"; {len(paths) - 3} more declared paths" if len(paths) > 3 else ""
        typer.echo(f"Scope: {shown}{remaining}")
    else:
        typer.echo("Scope: no paths declared; establish task ownership before checkpointing changed files.")
    if criteria := task.get("done_when"):
        typer.echo("Done when: " + " | ".join(criteria))
    context = task.get("context") or {}
    requirements = task.get("completion_requirements") or context.get("completion_requirements") or {}
    if requirements.get("deployment") or requirements.get("live_checks"):
        typer.echo(f"Runtime evidence: deployment={bool(requirements.get('deployment'))}; checks={','.join(requirements.get('live_checks') or [])}")
    typer.echo(f"Next: develop and use st done {task_id} for local completion; st context {task_id} has full details.")


def print_resumed(task_id: str, _result: dict[str, Any]) -> None:
    """Print output for a resumed task."""
    output_success(f"Task {task_id} resumed on current checkout.")
    _print_claim_brief(task_id, _result)


def print_claimed(task_id: str, _result: dict[str, Any]) -> None:
    """Print output for a newly claimed task."""
    output_success(f"Task {task_id} claimed. Checkpoint recorded; work commits direct to main.")
    _print_claim_brief(task_id, _result)
