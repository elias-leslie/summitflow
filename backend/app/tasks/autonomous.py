"""Autonomous task execution - Re-exports for backward compatibility.

This module re-exports from the autonomous package.
Import directly from app.tasks.autonomous.* for new code.
"""

from __future__ import annotations

# Re-export Celery tasks (these register with Celery on import)
# Re-export filter functions for backward compatibility
# Re-export config
# Re-export utils
from .autonomous import (
    ALLOWED_TASK_IDS,
    AUTONOMOUS_DRY_RUN,
    VALIDATION_MODE,
    autonomous_work_pickup,
    check_exclusion,
    count_domains,
    generate_bug_tasks,
    generate_tasks_from_scan,
    get_project_repo_path,
    has_standalone_label,
    is_blocklisted_error,
    is_exploratory,
    is_security_sensitive,
    is_standalone,
    reset_expired_task_claims,
    review_pending_tasks,
)

__all__ = [
    "ALLOWED_TASK_IDS",
    "AUTONOMOUS_DRY_RUN",
    "VALIDATION_MODE",
    "autonomous_work_pickup",
    "check_exclusion",
    "count_domains",
    "generate_bug_tasks",
    "generate_tasks_from_scan",
    "get_project_repo_path",
    "has_standalone_label",
    "is_blocklisted_error",
    "is_exploratory",
    "is_security_sensitive",
    "is_standalone",
    "reset_expired_task_claims",
    "review_pending_tasks",
]
