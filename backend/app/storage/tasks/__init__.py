"""Tasks storage package - Task CRUD, status, claims, and queries.

This package provides data access for agent execution tasks.

Modules:
    core: CRUD operations
    columns: Column definitions and constants
    mapping: Row to dict conversions
    update: Update operations
    sessions: Agent Hub session management
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
from .dedup import bug_task_exists_for_error, duplicate_task_exists, task_exists_for_file
from .queries import (
    count_completed_tasks_today,
    count_tasks,
    get_stale_tasks,
    get_tasks_by_enrichment_status,
    list_blocked_tasks,
    list_ready_tasks,
    list_tasks,
)
from .sessions import add_agent_hub_session, get_agent_hub_sessions
from .status import (
    VALID_TRANSITIONS,
    add_commit,
    update_task_status,
    validate_status_transition,
)

__all__ = [
    "EXPECTED_TASK_COLUMNS",
    "TASK_COLUMNS",
    "TASK_COLUMNS_ALIASED",
    "VALID_TRANSITIONS",
    "_row_to_dict",
    "add_agent_hub_session",
    "add_commit",
    "bug_task_exists_for_error",
    "claim_task",
    "count_completed_tasks_today",
    "count_running_tasks",
    "count_tasks",
    "create_task",
    "delete_task",
    "duplicate_task_exists",
    "get_agent_hub_sessions",
    "get_stale_tasks",
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
