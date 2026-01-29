"""Git worktree commands for the CLI."""

from __future__ import annotations

import subprocess
from typing import Annotated

import typer

from ..config import get_config
from ..context import require_task_id
from ..output import output_error, output_json, output_success
from .worktree_commands import (
    create_worktree_impl,
    list_worktrees_impl,
    merge_worktree_impl,
    remove_worktree_impl,
    worktree_status_impl,
)
from .worktree_git_ops import get_project_root
from .worktree_helpers import cleanup_empty_directories

app = typer.Typer(help="Git worktree management")


@app.command("list")
def list_worktrees(
    all_projects: Annotated[
        bool, typer.Option("--all", "-a", help="Show worktrees for all projects")
    ] = False,
) -> None:
    """List active git worktrees for the current project.

    Shows worktrees in /tmp/st-worktrees/{project_id}/ with linked task info.

    Examples:
        st worktree list
        st worktree list --all
    """
    config = get_config()
    project_root = get_project_root()
    list_worktrees_impl(config, project_root, all_projects)


@app.command()
def prune(
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    all_projects: Annotated[
        bool, typer.Option("--all", "-a", help="Prune worktrees for all projects")
    ] = False,
) -> None:
    """Clean up orphaned worktrees.

    Removes worktree metadata for directories that no longer exist.

    Examples:
        st worktree prune
        st worktree prune --dry-run
        st worktree prune --all
    """
    config = get_config()
    project_root = get_project_root()

    # Run git worktree prune
    try:
        args = ["git", "worktree", "prune"]
        if dry_run:
            args.append("--dry-run")

        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=str(project_root),
        )

        if result.returncode == 0:
            if dry_run:
                output_json({"dry_run": True, "would_prune": result.stdout or None})
            else:
                output_success("Pruned orphaned worktree metadata")

                # Also clean up empty directories in worktree base
                removed_dirs = cleanup_empty_directories(config.project_id, all_projects)

                if removed_dirs:
                    output_json({"removed_empty_dirs": removed_dirs})
        else:
            output_error(f"Failed to prune: {result.stderr}")

    except Exception as e:
        output_error(f"Failed to prune worktrees: {e}")
        raise typer.Exit(1) from None


@app.command("create")
def create_worktree(
    task_id: Annotated[
        str | None,
        typer.Argument(help="Task ID (uses active task if not provided)"),
    ] = None,
) -> None:
    """Create a worktree for executing a task in isolation.

    Creates a new git worktree at /tmp/summitflow-worktrees/{project_id}/{task_id}
    with branch exec/{task_id} based on the main branch.

    If a worktree already exists for this task, returns its info.

    Examples:
        st worktree create              # Uses active task
        st worktree create task-abc123  # Explicit task
    """
    config = get_config()
    resolved_task_id = require_task_id(task_id)

    try:
        create_worktree_impl(config, resolved_task_id)
    except Exception as e:
        output_error(f"Failed to create worktree: {e}")
        raise typer.Exit(1) from None


@app.command("status")
def worktree_status(
    task_id: Annotated[
        str | None,
        typer.Argument(help="Task ID (uses active task if not provided)"),
    ] = None,
) -> None:
    """Show status of worktree for a task.

    Returns worktree path, branch, commit count, and files changed.

    Examples:
        st worktree status              # Uses active task
        st worktree status task-abc123  # Explicit task
    """
    config = get_config()
    resolved_task_id = require_task_id(task_id)

    try:
        worktree_status_impl(config, resolved_task_id)
        # Exit with error if worktree doesn't exist
        from .worktree_helpers import get_worktree_manager

        manager = get_worktree_manager()
        if not manager.get_worktree_info(config.project_id, resolved_task_id):
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        output_error(f"Failed to get worktree status: {e}")
        raise typer.Exit(1) from None


@app.command("merge")
def merge_worktree(
    task_id: Annotated[
        str | None,
        typer.Argument(help="Task ID (uses active task if not provided)"),
    ] = None,
    keep: Annotated[
        bool,
        typer.Option("--keep", "-k", help="Keep worktree after merge"),
    ] = False,
    no_commit: Annotated[
        bool,
        typer.Option("--no-commit", help="Stage changes without committing"),
    ] = False,
    check_blast_radius: Annotated[
        bool,
        typer.Option(
            "--check-blast-radius/--no-check-blast-radius", help="Check blast radius before merge"
        ),
    ] = True,
) -> None:
    """Merge worktree branch back to main branch.

    Performs a no-fast-forward merge of the task's exec/{task_id} branch
    into the base branch. By default, removes the worktree after merge.

    Examples:
        st worktree merge               # Merge and cleanup
        st worktree merge --keep        # Merge but keep worktree
        st worktree merge --no-commit   # Stage only, no commit
    """
    config = get_config()
    resolved_task_id = require_task_id(task_id)

    try:
        success = merge_worktree_impl(config, resolved_task_id, keep, no_commit, check_blast_radius)
        if not success:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        output_error(f"Failed to merge worktree: {e}")
        raise typer.Exit(1) from None


@app.command("remove")
def remove_worktree(
    task_id: Annotated[
        str | None,
        typer.Argument(help="Task ID (uses active task if not provided)"),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Force remove even with uncommitted changes"),
    ] = False,
    keep_branch: Annotated[
        bool,
        typer.Option("--keep-branch", help="Keep the exec/{task_id} branch"),
    ] = False,
) -> None:
    """Remove a worktree without merging.

    Use this for cleanup when a task is cancelled or failed.
    The exec/{task_id} branch is deleted by default.

    Examples:
        st worktree remove              # Remove active task's worktree
        st worktree remove task-abc123  # Remove specific worktree
        st worktree remove --keep-branch # Keep the branch for later
    """
    config = get_config()
    resolved_task_id = require_task_id(task_id)

    try:
        success = remove_worktree_impl(config, resolved_task_id, force, keep_branch)
        if not success:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        output_error(f"Failed to remove worktree: {e}")
        raise typer.Exit(1) from None
