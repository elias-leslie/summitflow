"""Orphan branch salvage helpers for cleanup commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from app.storage import tasks as task_store
from app.utils._git_branches import assess_orphan_task_branches
from app.utils._git_core import run_git

from ..lib.checkpoint_metadata import SnapshotMeta, get_claimed_by, save_snapshot_meta
from ..output import output_error, output_success


def get_orphan_assessment(repo_path: Path, task_id: str) -> object | None:
    """Return orphan assessment for task_id in repo_path, if any."""
    for item in assess_orphan_task_branches(repo_path):
        if item.task_id == task_id:
            return item
    return None


def get_branch_subject(repo_path: Path, branch_name: str) -> str | None:
    """Return the latest commit subject for a branch."""
    result = run_git(["log", "-1", "--format=%s", branch_name], repo_path)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def build_salvage_description(task_id: str, branch_name: str, repo_path: Path) -> str:
    """Build a compact description for a recovered orphan branch task."""
    subject = get_branch_subject(repo_path, branch_name)
    detail = f"Latest commit: {subject}." if subject else "Latest commit subject unavailable."
    return (
        f"Recovered from orphan branch {branch_name} in {repo_path.name}. "
        f"{detail} Resume review, salvage, or discard from the restored lane."
    )


def validate_salvage_candidate(item: object, task_id: str) -> bool:
    """Validate orphan item is salvage candidate; emit stable operator guidance if not."""
    resolution = getattr(item, "resolution", None)
    if resolution != "salvage":
        task_token = getattr(item, "task_token", None)
        detail = "task record still exists"
        if task_token == "task:unreadable":
            detail = "task record still exists but is unreadable"
        output_error(
            f"{task_id} is not a missing-task salvage candidate: {detail}. "
            "Open task context/manual reconcile instead."
        )
        return False
    return True


def coerce_created_at(value: Any) -> str:
    """Return JSON-safe checkpoint creation timestamp."""
    if value is None:
        return ""
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def recover_orphan_task(repo_path: Path, item: object, task_id: str) -> None:
    """Create task record and checkpoint metadata for a salvaged orphan branch."""
    branch_name = getattr(item, "branch_name", "")
    has_node_modules = getattr(item, "has_node_modules_artifact", False)
    title = get_branch_subject(repo_path, branch_name) or f"Recover orphan branch {task_id}"
    description = build_salvage_description(task_id, branch_name, repo_path)
    created = task_store.create_task(
        project_id=repo_path.name,
        title=title,
        description=description,
        task_id=task_id,
        labels=["cleanup:salvaged"],
    )
    task_store.update_task(task_id, branch_name=branch_name)
    original_branch = ""
    try:
        current = run_git(["branch", "--show-current"], repo_path)
        if current.returncode == 0:
            original_branch = current.stdout.strip()
        result = run_git(["checkout", branch_name], repo_path)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"Failed to checkout {branch_name}")
        save_snapshot_meta(
            SnapshotMeta(
                task_id=task_id,
                project_id=repo_path.name,
                base_branch="main",
                created_at=coerce_created_at(created.get("created_at")),
                claimed_by=get_claimed_by(),
            )
        )
    except Exception as exc:
        if original_branch and original_branch != branch_name:
            run_git(["checkout", original_branch], repo_path)
        task_store.delete_task(task_id, deletion_source="cli:cleanup.salvage_rollback")
        output_error(f"Recovered task record for {task_id}, but failed to restore the branch: {exc}")
        raise typer.Exit(1) from exc

    output_success(f"Recovered orphan branch {branch_name} into task {created['id']}")
    typer.echo(f"  project: {repo_path.name}")
    typer.echo(f"  title: {title}")
    typer.echo(f"  branch: {branch_name}")
    typer.echo(f"  cwd: {repo_path}")
    if has_node_modules:
        typer.echo("  note: branch includes node_modules artifact changes; inspect before merge")
