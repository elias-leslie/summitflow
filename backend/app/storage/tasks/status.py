"""Tasks storage - Status transitions and state machine.

Status values: pending, running, completed, failed, cancelled.

Simplified from 11 statuses to 5.
"""

from __future__ import annotations

from typing import Any

from ..connection import get_connection
from .core import TASK_COLUMNS, _row_to_dict, canonicalize_task_id, get_task

# Valid task status transitions (simplified)
VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running", "cancelled"},
    "running": {"completed", "failed", "cancelled", "pending"},
    "completed": {"pending"},
    "failed": {"pending", "running"},
    "cancelled": {"pending"},
}

# All valid status values (derived from transition keys)
VALID_STATUSES: frozenset[str] = frozenset(VALID_TRANSITIONS.keys())

# Prebuilt UPDATE SQL for status changes
_UPDATE_SQL = f"""
    UPDATE tasks SET status = %s,
        started_at = CASE WHEN %s = 'running' THEN COALESCE(started_at, NOW()) ELSE started_at END,
        completed_at = CASE
            WHEN %s IN ('completed','failed','cancelled') THEN NOW()
            WHEN %s IN ('pending','running') THEN NULL
            ELSE completed_at
        END,
        error_message = CASE WHEN %s = 'running' THEN NULL WHEN %s IN ('completed','failed') THEN %s ELSE error_message END,
        current_phase = CASE WHEN %s = 'completed' THEN 'complete' ELSE current_phase END,
        claimed_by = CASE WHEN %s IN ('completed','failed','cancelled') THEN NULL ELSE claimed_by END,
        claimed_at = CASE WHEN %s IN ('completed','failed','cancelled') THEN NULL ELSE claimed_at END,
        lock_expires_at = CASE WHEN %s IN ('completed','failed','cancelled') THEN NULL ELSE lock_expires_at END,
        updated_at = NOW()
    WHERE id = %s RETURNING {TASK_COLUMNS}
"""


def validate_status_transition(current: str, target: str) -> bool:
    """Check if a status transition is valid."""
    return target in VALID_TRANSITIONS.get(current, set())


def _check_transition(task_id: str, status: str) -> None:
    """Validate that the current task status can transition to *status*.

    Raises:
        ValueError: If the transition is not allowed.
    """
    current_task = get_task(task_id)
    if not current_task:
        return
    current_status = current_task["status"]
    if current_status != status and not validate_status_transition(current_status, status):
        raise ValueError(
            f"Invalid transition from '{current_status}' to '{status}'. "
            f"Valid transitions: {VALID_TRANSITIONS.get(current_status, set())}"
        )


def _execute_status_update(
    task_id: str, status: str, error_message: str | None
) -> dict[str, Any] | None:
    """Execute the status UPDATE SQL and return the updated row dict or None."""
    resolved_task_id = canonicalize_task_id(task_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            _UPDATE_SQL,
            (status, status, status, status, status, status, error_message,
             status, status, status, status, resolved_task_id),
        )
        row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row) if row else None


def update_task_status(
    task_id: str,
    status: str,
    error_message: str | None = None,
    validate_transition: bool = True,
) -> dict[str, Any] | None:
    """Update task status with timestamp handling and transition validation.

    Args:
        task_id: Task ID
        status: New status (pending, running, completed, failed, cancelled)
        error_message: Optional error message (for failed status)
        validate_transition: Whether to validate status transition (default True)

    Returns:
        Updated task dict or None if not found.

    Raises:
        ValueError: If invalid status or invalid transition.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {VALID_STATUSES}")
    if validate_transition:
        _check_transition(task_id, status)
    return _execute_status_update(task_id, status, error_message)


def add_commit(task_id: str, commit_sha: str) -> dict[str, Any] | None:
    """Add a commit SHA to the task's commits array.

    Args:
        task_id: Task ID
        commit_sha: Git commit SHA to add

    Returns:
        Updated task dict or None if not found.
    """
    resolved_task_id = canonicalize_task_id(task_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"UPDATE tasks SET commits = array_append(commits, %s) WHERE id = %s RETURNING {TASK_COLUMNS}",
            (commit_sha, resolved_task_id),
        )
        row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row) if row else None
