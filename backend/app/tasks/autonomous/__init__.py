"""Autonomous task execution Celery tasks.

This package provides Celery tasks for autonomous code execution:
- reset_expired_task_claims: Clean up stale task locks
- generate_tasks_from_scan: Create tasks from Explorer refactor targets
- generate_bug_tasks: DISABLED - was too noisy (environmental/transient errors)
- autonomous_work_pickup: Pick up and execute eligible tasks
- review_pending_tasks: Opus review gate for ai_reviewing tasks
- cleanup_orphaned_worktrees: Clean up stale worktrees

Modules:
- cleanup.py: Maintenance tasks (claim reset, worktree cleanup)
- execution.py: Work pickup and task execution
- review.py: Opus review orchestration
- task_filters.py: Eligibility and exclusion checks
- task_generation.py: Scan-to-task and bug-to-task generation
- utils.py: Shared helper functions
"""

from .cleanup import cleanup_orphaned_worktrees, reset_expired_task_claims
from .execution import autonomous_work_pickup
from .review import review_pending_tasks
from .task_filters import (
    ALLOWED_TASK_IDS,
    AUTONOMOUS_DRY_RUN,
    VALIDATION_MODE,
    check_exclusion,
    count_domains,
    has_standalone_label,
    is_blocklisted_error,
    is_exploratory,
    is_security_sensitive,
    is_standalone,
)
from .task_generation import generate_bug_tasks, generate_tasks_from_scan
from .utils import get_project_repo_path

__all__ = [
    "ALLOWED_TASK_IDS",
    "AUTONOMOUS_DRY_RUN",
    "VALIDATION_MODE",
    "autonomous_work_pickup",
    "check_exclusion",
    "cleanup_orphaned_worktrees",
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
