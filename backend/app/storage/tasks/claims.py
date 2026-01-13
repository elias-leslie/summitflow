"""Tasks storage - Claim/release operations for distributed execution.

This module handles task locking for concurrent worker access.
"""

from __future__ import annotations

from typing import Any

from ..connection import get_connection
from .core import TASK_COLUMNS, _row_to_dict


def claim_task(
    task_id: str,
    worker_id: str,
    lock_duration_minutes: int = 30,
) -> dict[str, Any] | None:
    """Atomically claim a task for execution.

    Uses SELECT FOR UPDATE to prevent race conditions when multiple workers
    try to claim the same task.

    Args:
        task_id: Task ID to claim
        worker_id: Identifier for the worker claiming the task
        lock_duration_minutes: How long the claim is valid (default 30 min)

    Returns:
        Claimed task dict if successful, None if:
        - Task not found
        - Task status not claimable (not pending/paused/failed)
        - Task already claimed by another worker with valid lock
    """
    with get_connection() as conn, conn.cursor() as cur:
        # SELECT FOR UPDATE locks the row until transaction commits
        cur.execute(
            f"""
            SELECT {TASK_COLUMNS}
            FROM tasks
            WHERE id = %s
            FOR UPDATE
            """,
            (task_id,),
        )
        row = cur.fetchone()

        if not row:
            return None

        task = _row_to_dict(row)

        # Check if task is in a claimable status
        # Includes paused (legacy) and blocked (agent workflow)
        claimable_statuses = {"pending", "paused", "blocked", "failed"}
        if task["status"] not in claimable_statuses:
            return None

        # Check if already claimed with valid lock
        if task["claimed_by"] and task["lock_expires_at"]:
            # Check if lock is still valid
            cur.execute("SELECT NOW()")
            now_row = cur.fetchone()
            assert now_row is not None, "SELECT NOW() should always return a row"
            now = now_row[0]
            if task["lock_expires_at"] > now:
                # Another worker has a valid claim
                return None

        # Claim the task
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
            (worker_id, lock_duration_minutes, task_id),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        return None
    return _row_to_dict(row)


def release_task(task_id: str) -> dict[str, Any] | None:
    """Release a claimed task back to pending status.

    Clears the claim fields and resets status to pending.

    Args:
        task_id: Task ID to release

    Returns:
        Updated task dict or None if not found.
    """
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
            (task_id,),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        return None
    return _row_to_dict(row)


def reset_expired_claims() -> int:
    """Reset all tasks with expired claim locks.

    Finds tasks where:
    - status is 'running'
    - lock_expires_at has passed
    - claimed_by is set

    Resets them to 'pending' with cleared claim fields.

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

    Args:
        project_id: Project ID

    Returns:
        Number of tasks with status='running' and valid claim
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
