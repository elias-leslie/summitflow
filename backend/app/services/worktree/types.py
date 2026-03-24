"""Worktree type definitions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class TaskWorktreeInfo:
    """Information about a task's worktree."""

    path: Path
    branch: str
    task_id: str
    base_branch: str
    is_active: bool = True


__all__ = [
    "TaskWorktreeInfo",
]
