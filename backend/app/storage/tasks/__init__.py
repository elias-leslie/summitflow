"""Tasks storage package - Task CRUD, status, claims, and queries.

This package provides data access for agent execution tasks.

Modules:
    core: CRUD operations and row mapping
    status: State machine and status transitions
    claims: Distributed locking for concurrent execution
    queries: Task listing, filtering, and ready/blocked queries
    dedup: Semantic deduplication helpers
"""

from .claims import claim_task, count_running_tasks, release_task, reset_expired_claims
from .core import (
    EXPECTED_TASK_COLUMNS,
    TASK_COLUMNS,
    TASK_COLUMNS_ALIASED,
    _row_to_dict,
    create_task,
    delete_task,
    get_task,
    update_task,
)
from .dedup import bug_task_exists_for_error, task_exists_for_file
from .queries import (
    get_tasks_by_enrichment_status,
    list_blocked_tasks,
    list_ready_tasks,
    list_tasks,
)
from .status import (
    VALID_TRANSITIONS,
    add_commit,
    append_progress_log,
    update_task_status,
    validate_status_transition,
)

__all__ = [
    "EXPECTED_TASK_COLUMNS",
    "TASK_COLUMNS",
    "TASK_COLUMNS_ALIASED",
    "VALID_TRANSITIONS",
    "_row_to_dict",
    "add_commit",
    "append_progress_log",
    "bug_task_exists_for_error",
    "claim_task",
    "count_running_tasks",
    "create_task",
    "delete_task",
    "get_task",
    "get_tasks_by_enrichment_status",
    "list_blocked_tasks",
    "list_ready_tasks",
    "list_tasks",
    "release_task",
    "reset_expired_claims",
    "task_exists_for_file",
    "update_task",
    "update_task_status",
    "validate_status_transition",
]
