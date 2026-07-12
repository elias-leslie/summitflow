"""Tasks storage - Status transitions and state machine.

Status values: pending, running, paused, completed, failed, cancelled.

Simplified from legacy multi-stage statuses to the lifecycle states used by st.
"""

from __future__ import annotations

from typing import Any

from ..connection import get_connection
from .core import TASK_COLUMNS, _row_to_dict, canonicalize_task_id

# Valid task status transitions (simplified)
VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running", "paused", "cancelled"},
    "running": {"completed", "failed", "cancelled", "pending", "paused"},
    "paused": {"pending", "running", "cancelled"},
    "completed": {"pending", "cancelled"},
    "failed": {"pending", "running", "cancelled", "completed"},
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
            WHEN %s IN ('pending','running','paused') THEN NULL
            ELSE completed_at
        END,
        error_message = CASE WHEN %s IN ('pending','running','paused') THEN NULL WHEN %s IN ('completed','failed','cancelled') THEN %s ELSE error_message END,
        verification_result = CASE WHEN %s = 'completed' THEN verification_result ELSE NULL END,
        current_phase = CASE WHEN %s = 'completed' THEN 'complete' ELSE current_phase END,
        claimed_by = CASE WHEN %s IN ('completed','failed','cancelled','paused') THEN NULL ELSE claimed_by END,
        claimed_at = CASE WHEN %s IN ('completed','failed','cancelled','paused') THEN NULL ELSE claimed_at END,
        lock_expires_at = CASE WHEN %s IN ('completed','failed','cancelled','paused') THEN NULL ELSE lock_expires_at END,
        updated_at = NOW()
    WHERE id = %s RETURNING {TASK_COLUMNS}
"""


def validate_status_transition(current: str, target: str) -> bool:
    """Check if a status transition is valid."""
    return target in VALID_TRANSITIONS.get(current, set())


def _check_transition(current_status: str, status: str) -> None:
    """Validate a locked current status can transition to *status*."""
    if current_status != status and not validate_status_transition(current_status, status):
        raise ValueError(
            f"Invalid transition from '{current_status}' to '{status}'. "
            f"Valid transitions: {VALID_TRANSITIONS.get(current_status, set())}"
        )


def _execute_status_update(
    task_id: str,
    status: str,
    error_message: str | None,
    *,
    validate_transition: bool,
) -> dict[str, Any] | None:
    """Validate and update status atomically under a row lock."""
    resolved_task_id = canonicalize_task_id(task_id)
    with get_connection() as conn, conn.cursor() as cur:
        if validate_transition:
            cur.execute(
                "SELECT status FROM tasks WHERE id = %s FOR UPDATE",
                (resolved_task_id,),
            )
            current_row = cur.fetchone()
            if not current_row:
                return None
            _check_transition(str(current_row[0]), status)
        cur.execute(
            _UPDATE_SQL,
            (
                status,
                status,
                status,
                status,
                status,
                status,
                error_message,
                status,
                status,
                status,
                status,
                status,
                resolved_task_id,
            ),
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
        status: New status (pending, running, paused, completed, failed, cancelled)
        error_message: Optional error message (for failed status)
        validate_transition: Whether to validate status transition (default True)

    Returns:
        Updated task dict or None if not found.

    Raises:
        ValueError: If invalid status or invalid transition.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {VALID_STATUSES}")
    return _execute_status_update(
        task_id,
        status,
        error_message,
        validate_transition=validate_transition,
    )


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
