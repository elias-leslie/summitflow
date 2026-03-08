"""Shared workspace hygiene summaries for project coordination surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.storage.projects import get_project_root_path
from app.utils._git_branches import build_repo_workspace_summary

from cli.commands.cleanup_git import has_uncommitted_changes
from cli.lib.worktree import get_active_worktrees


def build_project_cleanup_status(project_id: str) -> dict[str, Any]:
    """Return cleanup/worktree summary for one managed repository."""
    root_path = get_project_root_path(project_id)
    if not root_path:
        return {
            "project_id": project_id,
            "path": None,
            "active_worktrees": 0,
            "dirty_worktrees": 0,
            "orphan_task_branches": 0,
            "prunable_task_branches": 0,
            "worktree_task_ids": [],
            "needs_cleanup": False,
        }

    repo_path = Path(root_path)
    workspace_summary = build_repo_workspace_summary(repo_path)
    active_worktrees = get_active_worktrees(project_id)
    dirty_worktrees = sum(
        1 for worktree in active_worktrees if has_uncommitted_changes(worktree.path)
    )
    needs_cleanup = any(
        (
            dirty_worktrees,
            workspace_summary.orphan_branches,
            workspace_summary.prunable_branches,
        )
    )
    return {
        "project_id": project_id,
        "path": str(repo_path),
        "active_worktrees": workspace_summary.active_worktrees,
        "dirty_worktrees": dirty_worktrees,
        "orphan_task_branches": workspace_summary.orphan_branches,
        "prunable_task_branches": workspace_summary.prunable_branches,
        "worktree_task_ids": workspace_summary.worktree_task_ids,
        "needs_cleanup": needs_cleanup,
    }
