"""Git worktree commands for the CLI."""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Annotated, Any

import typer

from ..config import get_config
from ..context import get_active_context, require_task_id
from ..output import output_error, output_json, output_success

app = typer.Typer(help="Git worktree management")

# Base directory for all worktrees (project-agnostic)
# Note: WorktreeManager uses /tmp/summitflow-worktrees by default
WORKTREE_BASE = Path("/tmp/st-worktrees")


def _get_project_root() -> Path:
    """Get the current project's root directory."""
    config = get_config()
    if config.project_root:
        return Path(config.project_root)
    # Fallback: try to find git root from cwd
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=Path.cwd(),
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except Exception:
        pass
    # Last resort: use cwd
    return Path.cwd()


def _get_worktrees_from_git(project_root: Path) -> list[dict[str, Any]]:
    """Get worktrees from git worktree list.

    Args:
        project_root: Root directory of the git repository
    """
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            cwd=str(project_root),
        )
        if result.returncode != 0:
            return []

        worktrees: list[dict[str, Any]] = []
        current: dict[str, Any] = {}
        for line in result.stdout.strip().split("\n"):
            if not line:
                if current:
                    worktrees.append(current)
                    current = {}
                continue
            if line.startswith("worktree "):
                current["path"] = line[9:]
            elif line.startswith("HEAD "):
                current["head"] = line[5:]
            elif line.startswith("branch "):
                current["branch"] = line[7:]

        if current:
            worktrees.append(current)

        return worktrees
    except Exception:
        return []


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
    project_root = _get_project_root()

    # Get worktrees from git
    git_worktrees = _get_worktrees_from_git(project_root)

    # Filter to st-worktrees
    if all_projects:
        # Show all worktrees under st-worktrees base
        worktrees = [w for w in git_worktrees if "st-worktrees" in w.get("path", "")]
    else:
        # Filter to current project's worktrees
        project_worktree_dir = str(WORKTREE_BASE / config.project_id)
        worktrees = [w for w in git_worktrees if w.get("path", "").startswith(project_worktree_dir)]

    # Extract task_id and project_id from worktree directory names
    for w in worktrees:
        path = w.get("path", "")
        # Worktree directories are named like: /tmp/st-worktrees/{project_id}/{task_id}
        parts = path.split("/")
        if len(parts) >= 2:
            potential_task_id = parts[-1]
            if potential_task_id.startswith("task-"):
                w["task_id"] = potential_task_id
            # Project ID is second to last
            if len(parts) >= 3:
                w["project_id"] = parts[-2]

        # Add status
        w["status"] = "active" if os.path.exists(path) else "orphaned"

    output_json({"worktrees": worktrees, "project_id": config.project_id})


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
    project_root = _get_project_root()

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
                removed_dirs = []
                if WORKTREE_BASE.exists():
                    config = get_config()
                    if all_projects:
                        # Clean all project directories
                        dirs_to_check = list(WORKTREE_BASE.iterdir())
                    else:
                        # Only clean current project's directory
                        project_dir = WORKTREE_BASE / config.project_id
                        dirs_to_check = [project_dir] if project_dir.exists() else []

                    for project_dir in dirs_to_check:
                        if project_dir.is_dir():
                            for task_dir in project_dir.iterdir():
                                if task_dir.is_dir() and not any(task_dir.iterdir()):
                                    task_dir.rmdir()
                                    removed_dirs.append(str(task_dir))
                            if not any(project_dir.iterdir()):
                                project_dir.rmdir()
                                removed_dirs.append(str(project_dir))

                if removed_dirs:
                    output_json({"removed_empty_dirs": removed_dirs})
        else:
            output_error(f"Failed to prune: {result.stderr}")

    except Exception as e:
        output_error(f"Failed to prune worktrees: {e}")
        raise typer.Exit(1) from None


def _get_worktree_manager() -> "WorktreeManager":
    """Get WorktreeManager instance for current project."""
    from app.services.worktree_manager import WorktreeManager

    project_root = _get_project_root()
    return WorktreeManager(project_root)


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
        manager = _get_worktree_manager()
        info = manager.get_or_create_worktree(config.project_id, resolved_task_id)

        output_json({
            "path": str(info.path),
            "branch": info.branch,
            "task_id": info.task_id,
            "project_id": info.project_id,
            "base_branch": info.base_branch,
            "is_active": info.is_active,
            "created": not manager.worktree_exists(config.project_id, resolved_task_id),
        })
        output_success(f"Worktree ready at {info.path}")

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
        manager = _get_worktree_manager()
        info = manager.get_worktree_info(config.project_id, resolved_task_id)

        if not info:
            output_json({
                "exists": False,
                "task_id": resolved_task_id,
                "project_id": config.project_id,
            })
            output_error(f"No worktree exists for task {resolved_task_id}")
            raise typer.Exit(1)

        # Get changed files list
        changed_files = manager.get_changed_files(config.project_id, resolved_task_id)

        output_json({
            "exists": True,
            "path": str(info.path),
            "branch": info.branch,
            "task_id": info.task_id,
            "project_id": info.project_id,
            "base_branch": info.base_branch,
            "is_active": info.is_active,
            "commit_count": info.commit_count,
            "files_changed": info.files_changed,
            "additions": info.additions,
            "deletions": info.deletions,
            "changed_files": [{"status": s, "path": p} for s, p in changed_files],
        })

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
        typer.Option("--check-blast-radius/--no-check-blast-radius", help="Check blast radius before merge"),
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
        manager = _get_worktree_manager()
        info = manager.get_worktree_info(config.project_id, resolved_task_id)

        if not info:
            output_error(f"No worktree exists for task {resolved_task_id}")
            raise typer.Exit(1)

        # Check blast radius if enabled
        if check_blast_radius:
            blast = manager.check_blast_radius(config.project_id, resolved_task_id)
            if not blast["passed"]:
                output_json({
                    "blast_radius_exceeded": True,
                    "files_changed": blast["files_changed"],
                    "deletions": blast["deletions"],
                    "reason": blast["reason"],
                })
                output_error(f"Blast radius check failed: {blast['reason']}")
                output_error("Use --no-check-blast-radius to force merge")
                raise typer.Exit(1)

        # Check for merge conflicts
        conflicts = manager.check_merge_conflicts(config.project_id, resolved_task_id)
        if conflicts["has_conflicts"]:
            output_json({
                "has_conflicts": True,
                "conflicting_files": conflicts["conflicting_files"],
            })
            output_error(f"Merge conflicts detected in: {', '.join(conflicts['conflicting_files'])}")
            raise typer.Exit(1)

        # Perform the merge
        success = asyncio.run(
            manager.merge_worktree(
                config.project_id,
                resolved_task_id,
                delete_after=not keep,
                no_commit=no_commit,
            )
        )

        if success:
            output_json({
                "merged": True,
                "branch": info.branch,
                "base_branch": info.base_branch,
                "worktree_removed": not keep,
                "committed": not no_commit,
            })
            if no_commit:
                output_success(f"Changes from {info.branch} staged for review")
            else:
                output_success(f"Merged {info.branch} into {info.base_branch}")
        else:
            output_error("Merge failed - check git status for details")
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
        manager = _get_worktree_manager()
        info = manager.get_worktree_info(config.project_id, resolved_task_id)

        if not info:
            output_json({
                "exists": False,
                "task_id": resolved_task_id,
            })
            output_error(f"No worktree exists for task {resolved_task_id}")
            raise typer.Exit(1)

        # Check for uncommitted changes if not forcing
        if not force:
            # Check for staged/unstaged changes in worktree (excluding untracked)
            result = subprocess.run(
                ["git", "status", "--porcelain", "-uno"],
                capture_output=True,
                text=True,
                cwd=str(info.path),
            )
            if result.stdout.strip():
                output_json({
                    "has_uncommitted_changes": True,
                    "path": str(info.path),
                })
                output_error("Worktree has uncommitted changes. Use --force to remove anyway.")
                raise typer.Exit(1)

        manager.remove_worktree(
            config.project_id,
            resolved_task_id,
            delete_branch=not keep_branch,
        )

        output_json({
            "removed": True,
            "path": str(info.path),
            "branch": info.branch,
            "branch_deleted": not keep_branch,
        })
        output_success(f"Removed worktree at {info.path}")

    except typer.Exit:
        raise
    except Exception as e:
        output_error(f"Failed to remove worktree: {e}")
        raise typer.Exit(1) from None
