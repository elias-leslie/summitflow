"""Background tasks for autonomous system maintenance and cleanup."""

from __future__ import annotations

from .checkpoint_cleanup import cleanup_task_checkpoint
from .merge_operations import (
    _auto_rollback,
    _run_post_merge_validation,
    merge_and_cleanup_task_checkpoint,
)
from .task_claims import reset_expired_task_claims

__all__ = [
    "_auto_rollback",
    "_run_post_merge_validation",
    "cleanup_task_checkpoint",
    "merge_and_cleanup_task_checkpoint",
    "reset_expired_task_claims",
]
