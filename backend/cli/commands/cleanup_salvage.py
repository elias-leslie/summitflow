"""Orphan branch salvage helpers for cleanup commands."""

from __future__ import annotations

from pathlib import Path

import typer

from app.storage import tasks as task_store
from app.utils._git_branches import assess_orphan_task_branches
from app.utils._git_core import run_git

from ..lib.worktree import create_worktree
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
    """Validate the orphan item is a salvage candidate; emit error and return False if not."""
    resolution = getattr(item, "resolution", None)
    task_status = getattr(item, "task_status", None)
    if resolution != "salvage" or task_status is not None:
        output_error(
            f"{task_id} is not a missing-task salvage candidate. "
            "This command only restores orphan branches whose task record is gone."
        )
        return False
    return True


def recover_orphan_task(repo_path: Path, item: object, task_id: str) -> None:
    """Create task record and worktree for a salvaged orphan branch."""
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
    try:
        worktree = create_worktree(task_id, project_id=repo_path.name)
    except Exception as exc:
        task_store.delete_task(task_id)
        output_error(f"Recovered task record for {task_id}, but failed to create worktree: {exc}")
        raise typer.Exit(1) from exc

    output_success(f"Recovered orphan branch {branch_name} into task {created['id']}")
    typer.echo(f"  project: {repo_path.name}")
    typer.echo(f"  title: {title}")
    typer.echo(f"  worktree: {worktree.path}")
    if has_node_modules:
        typer.echo("  note: branch includes node_modules artifact changes; inspect before merge")
