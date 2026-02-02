"""Tasks storage - Status transitions and state machine.

This module handles task status validation and updates.

Status values (extended for git management workflow):
- pending: Task created, not started
- running: Work in progress
- paused: Temporarily paused (human workflow) - maps to "blocked" concept
- failed: Task failed, can retry
- blocked: Task blocked by dependency or issue (agent workflow)
- pr_created: Pull request created, awaiting review
- ai_reviewing: AI review in progress
- human_review: Needs human review (escalated from AI)
- completed: Successfully completed
- cancelled: Task cancelled (auto-cancelled or never started)
- abandoned: Task was claimed but rolled back (append-only, never deleted)

Kanban column mapping (5 columns per decision d2):
- Planning: pending
- In Progress: running, paused, blocked
- AI Review: pr_created, ai_reviewing
- Human Review: human_review
- Done: completed, failed, cancelled, abandoned
"""

from __future__ import annotations

from typing import Any

from ..connection import get_connection
from .core import TASK_COLUMNS, _row_to_dict, get_task

# Valid task status transitions (extended for git management workflow)
VALID_TRANSITIONS: dict[str, set[str]] = {
    # Initial state
    "pending": {"queue", "running", "paused", "blocked", "cancelled"},
    # Queue state (autonomous execution pipeline)
    "queue": {"running", "pending", "blocked", "cancelled", "human_review"},
    # Work states - can transition to abandoned (rollback without DB restore)
    "running": {
        "queue",
        "paused",
        "failed",
        "blocked",
        "pr_created",
        "completed",
        "ai_reviewing",
        "human_reviewing",
        "needs_review",
        "cancelled",
        "abandoned",
    },
    "paused": {"queue", "running", "pending", "failed", "cancelled", "abandoned"},
    "blocked": {"queue", "running", "pending", "failed", "cancelled", "abandoned"},
    "failed": {"queue", "pending", "running", "cancelled"},
    # PR/Review states (agent workflow)
    "pr_created": {"ai_reviewing", "human_review", "failed", "cancelled", "abandoned"},
    "ai_reviewing": {"completed", "human_review", "running", "failed", "abandoned"},
    "human_review": {"completed", "running", "cancelled", "abandoned"},
    # Verification workflow states (migration 073)
    "needs_review": {"completed", "running", "failed", "cancelled", "abandoned"},
    "human_reviewing": {"completed", "running", "failed", "cancelled", "abandoned"},
    # Terminal states
    "completed": {"failed", "pending"},  # Reopen if incorrectly closed
    "cancelled": set(),
    "abandoned": set(),  # Terminal - claimed but rolled back
}

# Status to kanban column mapping (6 columns with Queue)
STATUS_TO_KANBAN_COLUMN: dict[str, str] = {
    "pending": "Planning",
    "queue": "Queue",  # Queued for autonomous execution
    "running": "In Progress",
    "paused": "In Progress",
    "blocked": "In Progress",
    "pr_created": "AI Review",
    "ai_reviewing": "AI Review",
    "human_review": "Human Review",
    "needs_review": "Human Review",  # Awaiting QA signoff
    "human_reviewing": "Human Review",  # Criteria escalated to human
    "completed": "Done",
    "failed": "Done",
    "cancelled": "Done",
    "abandoned": "Done",  # Claimed but rolled back
}


def status_to_kanban_column(status: str) -> str:
    """Map task status to kanban column name.

    Args:
        status: Task status value

    Returns:
        Kanban column name (Planning, In Progress, AI Review, Human Review, Done)
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
        "human_review",
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
