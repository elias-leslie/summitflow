"""Tasks storage - Claim/release operations for distributed execution.

This module handles task locking for concurrent worker access.
"""

from __future__ import annotations

from typing import Any

from ..connection import get_connection
from .core import TASK_COLUMNS, _row_to_dict, canonicalize_task_id

_CLAIMABLE_STATUSES = {"pending", "paused", "blocked", "failed", "queue"}


def _has_valid_lock(task: dict[str, Any], cur: Any) -> bool:
    """Return True if the task has an unexpired claim lock."""
    if not (task["claimed_by"] and task["lock_expires_at"]):
        return False
    cur.execute("SELECT NOW()")
    now_row = cur.fetchone()
    assert now_row is not None, "SELECT NOW() should always return a row"
    return task["lock_expires_at"] > now_row[0]


def claim_task(
    task_id: str,
    worker_id: str,
    lock_duration_minutes: int = 30,
) -> dict[str, Any] | None:
    """Atomically claim a task for execution.

    Uses SELECT FOR UPDATE to prevent race conditions when multiple workers
    try to claim the same task.

    Returns:
        Claimed task dict if successful, None if task not found, not in a
        claimable status, or already claimed by another worker.
    """
    resolved_task_id = canonicalize_task_id(task_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {TASK_COLUMNS} FROM tasks WHERE id = %s FOR UPDATE",
            (resolved_task_id,),
        )
        row = cur.fetchone()
        if not row:
            return None

        task = _row_to_dict(row)
        if task["status"] not in _CLAIMABLE_STATUSES:
            return None
        if _has_valid_lock(task, cur):
            return None

        cur.execute(
            f"""
            UPDATE tasks
            SET claimed_by = %s,
                claimed_at = NOW(),
                lock_expires_at = NOW() + INTERVAL '%s minutes',
                status = 'running',
                started_at = COALESCE(started_at, NOW())
            WHERE id = %s
            RETURNING {TASK_COLUMNS}
            """,
            (worker_id, lock_duration_minutes, resolved_task_id),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        return None
    return _row_to_dict(row)


def release_task(task_id: str) -> dict[str, Any] | None:
    """Release a claimed task back to pending status.

    Returns:
        Updated task dict or None if not found.
    """
    resolved_task_id = canonicalize_task_id(task_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE tasks
            SET claimed_by = NULL,
                claimed_at = NULL,
                lock_expires_at = NULL,
                status = 'pending'
            WHERE id = %s
            RETURNING {TASK_COLUMNS}
            """,
            (resolved_task_id,),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        return None
    return _row_to_dict(row)


def reset_expired_claims() -> int:
    """Reset all tasks with expired claim locks to pending.

    Returns:
        Count of tasks reset.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE tasks
            SET claimed_by = NULL,
                claimed_at = NULL,
                lock_expires_at = NULL,
                status = 'pending'
            WHERE status = 'running'
              AND lock_expires_at IS NOT NULL
              AND lock_expires_at < NOW()
              AND claimed_by IS NOT NULL
            """
        )
        count = cur.rowcount
        conn.commit()

    return count


def count_running_tasks(project_id: str) -> int:
    """Count tasks currently running for a project.

    Returns:
        Number of tasks with status='running' and valid claim.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM tasks
            WHERE project_id = %s
              AND status = 'running'
              AND claimed_by IS NOT NULL
              AND (lock_expires_at IS NULL OR lock_expires_at > NOW())
            """,
            (project_id,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0
