"""Worktree isolation service for autonomous task execution.

Provides worktree operations for Agent Hub task dispatch workflow.
Each dispatched task gets an isolated worktree at:
    /srv/workspaces/lanes/<project-id>/<task-id>/ when the shared workspace is available
    ~/.local/share/st/worktrees/<project-id>/<task-id>/ otherwise

With branch naming:
    <task-id>/main

This module wraps the CLI worktree library for use in background tasks.
Creates checkpoint metadata for unified tracking via `st checkpoints`.
"""

from __future__ import annotations

from .operations import (
    create_task_worktree,
    get_task_worktree,
    remove_task_worktree,
)
from .paths import ensure_task_worktree, get_execution_path
from .types import TaskWorktreeInfo, WorktreeError

__all__ = [
    "TaskWorktreeInfo",
    "WorktreeError",
    "create_task_worktree",
    "ensure_task_worktree",
    "get_execution_path",
    "get_task_worktree",
    "remove_task_worktree",
]
