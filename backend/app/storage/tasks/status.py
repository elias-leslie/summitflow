"""Tasks storage - Status transitions and state machine.

This module handles task status validation and updates.

Status values:
- pending: Task created, not started
- running: Work in progress
- paused: Temporarily paused
- failed: Task failed, can retry
- blocked: Task blocked by dependency, issue, or escalation
- pr_created: Pull request created, awaiting review
- ai_reviewing: AI review in progress
- completed: Successfully completed
- cancelled: Task cancelled (auto-cancelled or never started)
- abandoned: Task was claimed but rolled back (append-only, never deleted)

Kanban column mapping (6 columns):
- Ideas: pending (crowdsourced)
- Planning: pending
- Queue: queue
- Active: running, paused, ai_reviewing, pr_created
- Blocked: blocked
- Done: completed, failed, cancelled, abandoned
"""

from __future__ import annotations

from typing import Any

from ..connection import get_connection
from .core import TASK_COLUMNS, _row_to_dict, get_task

# Valid task status transitions
VALID_TRANSITIONS: dict[str, set[str]] = {
    # Initial state
    "pending": {"queue", "running", "paused", "blocked", "cancelled"},
    # Queue state (autonomous execution pipeline)
    "queue": {"running", "pending", "blocked", "cancelled"},
    # Work states - can transition to abandoned (rollback without DB restore)
    "running": {
        "queue",
        "paused",
        "failed",
        "blocked",
        "pr_created",
        "completed",
        "ai_reviewing",
        "cancelled",
        "abandoned",
    },
    "paused": {"queue", "running", "pending", "failed", "cancelled", "abandoned"},
    "blocked": {"queue", "running", "pending", "failed", "cancelled", "abandoned"},
    "failed": {"queue", "pending", "running", "cancelled"},
    # PR/Review states (agent workflow)
    "pr_created": {"ai_reviewing", "blocked", "failed", "cancelled", "abandoned"},
    "ai_reviewing": {"completed", "blocked", "running", "failed", "abandoned"},
    # Terminal states
    "completed": {"failed", "pending"},  # Reopen if incorrectly closed
    "cancelled": set(),
    "abandoned": set(),  # Terminal - claimed but rolled back
}

# Status to kanban column mapping (6 columns)
STATUS_TO_KANBAN_COLUMN: dict[str, str] = {
    "pending": "Planning",
    "queue": "Queue",
    "running": "Active",
    "paused": "Active",
    "pr_created": "Active",
    "ai_reviewing": "Active",
    "blocked": "Blocked",
    "completed": "Done",
    "failed": "Done",
    "cancelled": "Done",
    "abandoned": "Done",
}


def status_to_kanban_column(status: str) -> str:
    """Map task status to kanban column name.

    Args:
        status: Task status value

    Returns:
        Kanban column name (Planning, Queue, Active, Blocked, Done)
    """
    return STATUS_TO_KANBAN_COLUMN.get(status, "Planning")


def validate_status_transition(current: str, target: str) -> bool:
    """Check if a status transition is valid.

    Args:
        current: Current task status
        target: Target task status

    Returns:
        True if transition is valid
    """
    return target in VALID_TRANSITIONS.get(current, set())


def update_task_status(
    task_id: str,
    status: str,
    error_message: str | None = None,
    validate_transition: bool = True,
) -> dict[str, Any] | None:
    """Update task status with timestamp handling and transition validation.

    Args:
        task_id: Task ID
        status: New status (see module docstring for valid values)
        error_message: Optional error message (for failed status)
        validate_transition: Whether to validate status transition (default True)

    Returns:
        Updated task dict or None if not found.

    Raises:
        ValueError: If invalid status or invalid transition.
    """
    valid_statuses = {
        "pending",
        "queue",
        "running",
        "paused",
        "failed",
        "blocked",
        "pr_created",
        "ai_reviewing",
        "completed",
        "cancelled",
        "abandoned",
    }
    if status not in valid_statuses:
        raise ValueError(f"Invalid status '{status}'. Must be one of: {valid_statuses}")

    # Get current status if validating transitions
    if validate_transition:
        current_task = get_task(task_id)
        if current_task:
            current_status = current_task["status"]
            if current_status != status and not validate_status_transition(current_status, status):
                raise ValueError(
                    f"Invalid transition from '{current_status}' to '{status}'. "
                    f"Valid transitions: {VALID_TRANSITIONS.get(current_status, set())}"
                )

    with get_connection() as conn, conn.cursor() as cur:
        # Single UPDATE with CASE expressions for conditional field updates
        cur.execute(
            f"""
            UPDATE tasks
            SET status = %s,
                started_at = CASE WHEN %s = 'running' THEN COALESCE(started_at, NOW()) ELSE started_at END,
                completed_at = CASE WHEN %s IN ('completed', 'failed', 'cancelled', 'abandoned') THEN NOW() ELSE completed_at END,
                error_message = CASE
                    WHEN %s = 'running' THEN NULL
                    WHEN %s IN ('completed', 'failed') THEN %s
                    ELSE error_message
                END,
                current_phase = CASE WHEN %s = 'completed' THEN 'complete' ELSE current_phase END,
                claimed_by = CASE WHEN %s IN ('completed', 'failed', 'cancelled', 'abandoned') THEN NULL ELSE claimed_by END,
                claimed_at = CASE WHEN %s IN ('completed', 'failed', 'cancelled', 'abandoned') THEN NULL ELSE claimed_at END,
                lock_expires_at = CASE WHEN %s IN ('completed', 'failed', 'cancelled', 'abandoned') THEN NULL ELSE lock_expires_at END
            WHERE id = %s
            RETURNING {TASK_COLUMNS}
            """,
            (
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
                task_id,
            ),
        )

        row = cur.fetchone()
        conn.commit()

    if not row:
        return None
    return _row_to_dict(row)


def add_commit(task_id: str, commit_sha: str) -> dict[str, Any] | None:
    """Add a commit SHA to the task's commits array.

    Args:
        task_id: Task ID
        commit_sha: Git commit SHA to add

    Returns:
        Updated task dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE tasks
            SET commits = array_append(commits, %s)
            WHERE id = %s
            RETURNING {TASK_COLUMNS}
            """,
            (commit_sha, task_id),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        return None
    return _row_to_dict(row)
