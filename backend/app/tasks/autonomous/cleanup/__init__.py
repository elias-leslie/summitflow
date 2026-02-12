"""Background tasks for autonomous system maintenance and cleanup.

Includes:
- Task claim expiration handling
- Worktree cleanup for completed/cancelled tasks
- Merge and cleanup for approved SIMPLE tasks
"""

from __future__ import annotations

from .merge_operations import (
    _auto_rollback,
    _run_post_merge_validation,
    merge_and_cleanup_task_worktree,
)
from .task_claims import reset_expired_task_claims
from .worktree_cleanup import cleanup_task_worktree

__all__ = [
    "_auto_rollback",
    "_run_post_merge_validation",
    "cleanup_task_worktree",
    "merge_and_cleanup_task_worktree",
    "reset_expired_task_claims",
]
