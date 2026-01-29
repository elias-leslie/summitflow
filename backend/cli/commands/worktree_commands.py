"""Command implementations for worktree management."""

from __future__ import annotations

import asyncio
import os
import subprocess

from ..config import Config
from ..output import output_error, output_json, output_success
from .worktree_git_ops import get_worktrees_from_git
from .worktree_helpers import WORKTREE_BASE, get_worktree_manager


def list_worktrees_impl(config: Config, project_root, all_projects: bool) -> None:
    """Implementation for list command."""
    # Get worktrees from git
    git_worktrees = get_worktrees_from_git(project_root)

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


def create_worktree_impl(config: Config, task_id: str) -> None:
    """Implementation for create command."""
    manager = get_worktree_manager()
    info = manager.get_or_create_worktree(config.project_id, task_id)

    output_json(
        {
            "path": str(info.path),
            "branch": info.branch,
            "task_id": info.task_id,
            "project_id": info.project_id,
            "base_branch": info.base_branch,
            "is_active": info.is_active,
            "created": not manager.worktree_exists(config.project_id, task_id),
        }
    )
    output_success(f"Worktree ready at {info.path}")


def worktree_status_impl(config: Config, task_id: str) -> None:
    """Implementation for status command."""
    manager = get_worktree_manager()
    info = manager.get_worktree_info(config.project_id, task_id)

    if not info:
        output_json(
            {
                "exists": False,
                "task_id": task_id,
                "project_id": config.project_id,
            }
        )
        output_error(f"No worktree exists for task {task_id}")
        return

    # Get changed files list
    changed_files = manager.get_changed_files(config.project_id, task_id)

    output_json(
        {
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
        }
    )


def merge_worktree_impl(
    config: Config,
    task_id: str,
    keep: bool,
    no_commit: bool,
    check_blast_radius: bool,
) -> bool:
    """Implementation for merge command. Returns True on success."""
    manager = get_worktree_manager()
    info = manager.get_worktree_info(config.project_id, task_id)

    if not info:
        output_error(f"No worktree exists for task {task_id}")
        return False

    # Check blast radius if enabled
    if check_blast_radius:
        blast = manager.check_blast_radius(config.project_id, task_id)
        if not blast["passed"]:
            output_json(
                {
                    "blast_radius_exceeded": True,
                    "files_changed": blast["files_changed"],
                    "deletions": blast["deletions"],
                    "reason": blast["reason"],
                }
            )
            output_error(f"Blast radius check failed: {blast['reason']}")
            output_error("Use --no-check-blast-radius to force merge")
            return False

    # Check for merge conflicts
    conflicts = manager.check_merge_conflicts(config.project_id, task_id)
    if conflicts["has_conflicts"]:
        output_json(
            {
                "has_conflicts": True,
                "conflicting_files": conflicts["conflicting_files"],
            }
        )
        output_error(
            f"Merge conflicts detected in: {', '.join(conflicts['conflicting_files'])}"
        )
        return False

    # Perform the merge
    success = asyncio.run(
        manager.merge_worktree(
            config.project_id,
            task_id,
            delete_after=not keep,
            no_commit=no_commit,
        )
    )

    if success:
        output_json(
            {
                "merged": True,
                "branch": info.branch,
                "base_branch": info.base_branch,
                "worktree_removed": not keep,
                "committed": not no_commit,
            }
        )
        if no_commit:
            output_success(f"Changes from {info.branch} staged for review")
        else:
            output_success(f"Merged {info.branch} into {info.base_branch}")
    else:
        output_error("Merge failed - check git status for details")

    return success


def remove_worktree_impl(
    config: Config,
    task_id: str,
    force: bool,
    keep_branch: bool,
) -> bool:
    """Implementation for remove command. Returns True on success."""
    manager = get_worktree_manager()
    info = manager.get_worktree_info(config.project_id, task_id)

    if not info:
        output_json(
            {
                "exists": False,
                "task_id": task_id,
            }
        )
        output_error(f"No worktree exists for task {task_id}")
        return False

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
            output_json(
                {
                    "has_uncommitted_changes": True,
                    "path": str(info.path),
                }
            )
            output_error("Worktree has uncommitted changes. Use --force to remove anyway.")
            return False

    manager.remove_worktree(
        config.project_id,
        task_id,
        delete_branch=not keep_branch,
    )

    output_json(
        {
            "removed": True,
            "path": str(info.path),
            "branch": info.branch,
            "branch_deleted": not keep_branch,
        }
    )
    output_success(f"Removed worktree at {info.path}")
    return True
