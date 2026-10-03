"""Tasks storage - Claim/release operations for distributed execution.

This module handles task locking for concurrent worker access.
"""

from __future__ import annotations

from typing import Any, LiteralString

from ...logging_config import get_logger
from ..connection import get_connection, get_cursor
from .core import TASK_COLUMNS, _row_to_dict, canonicalize_task_id

_CLAIMABLE_STATUSES = {"pending", "paused", "failed"}
_DEFAULT_LOCK_MINUTES = 30
logger = get_logger(__name__)


def _preserved_verification_sql(
    column: LiteralString = "verification_result", *, preserve_closeout: bool = False
) -> LiteralString:
    """Build the established lifecycle projection for durable task evidence."""
    evidence: LiteralString = f"""NULLIF(jsonb_strip_nulls(jsonb_build_object(
        'acceptance', CASE WHEN {column} ? 'acceptance' THEN
            {column}->'acceptance' ||
            '{{"state":"stale","reason":"task_lifecycle_changed_requires_acceptance"}}'::jsonb END,
        'deployment', {column}->'deployment',
        'live_validation', {column}->'live_validation',
        'publication_repair', {column}->'publication_repair'
    )), '{{}}'::jsonb)"""
    if not preserve_closeout:
        return evidence
    return f"""CASE WHEN {column}->'closeout'->>'state' IN ('pending', 'blocked')
        THEN COALESCE({evidence}, '{{}}'::jsonb) ||
            jsonb_build_object('closeout', {column}->'closeout')
        ELSE {evidence} END"""


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
    *,
    renew_only: bool = False,
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
        if task["status"] == "running":
            if task["claimed_by"] != worker_id:
                return None
            cur.execute(
                f"""
                UPDATE tasks
                SET lock_expires_at = NOW() + (%s * INTERVAL '1 minute'),
                    updated_at = NOW()
                WHERE id = %s AND status = 'running' AND claimed_by = %s
                RETURNING {TASK_COLUMNS}
                """,
                (lock_duration_minutes, resolved_task_id, worker_id),
            )
            row = cur.fetchone()
            conn.commit()
            return _row_to_dict(row) if row else None
        if renew_only:
            return None
        if task["status"] not in _CLAIMABLE_STATUSES:
            return None
        if _has_valid_lock(task, cur):
            return None

        cur.execute(
            f"""
            UPDATE tasks
            SET claimed_by = %s,
                claimed_at = NOW(),
                lock_expires_at = NOW() + (%s * INTERVAL '1 minute'),
                status = 'running',
                verification_result = {_preserved_verification_sql()},
                started_at = COALESCE(started_at, NOW()),
                updated_at = NOW()
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


def renew_task_claim(
    task_id: str,
    expected_worker_id: str,
    lock_duration_minutes: int = _DEFAULT_LOCK_MINUTES,
) -> dict[str, Any] | None:
    """Extend an active claim only while the exact worker still owns it."""
    resolved_task_id = canonicalize_task_id(task_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE tasks
            SET lock_expires_at = NOW() + (%s * INTERVAL '1 minute'),
                updated_at = NOW()
            WHERE id = %s AND status = 'running' AND claimed_by = %s
            RETURNING {TASK_COLUMNS}
            """,
            (lock_duration_minutes, resolved_task_id, expected_worker_id),
        )
        row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row) if row else None


def release_task(
    task_id: str,
    *,
    expected_worker_id: str | None = None,
) -> dict[str, Any] | None:
    """Release a claimed task back to pending status.

    When ``expected_worker_id`` is provided, the release is compare-and-swap:
    it succeeds only while that worker still owns the claim. This prevents a
    delayed dispatch failure from releasing a newer worker's claim.

    Returns:
        Updated task dict or None if not found.
    """
    resolved_task_id = canonicalize_task_id(task_id)
    owner_clause = " AND claimed_by = %s" if expected_worker_id is not None else ""
    params = (
        (resolved_task_id,)
        if expected_worker_id is None
        else (resolved_task_id, expected_worker_id)
    )
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE tasks
            SET claimed_by = NULL,
                claimed_at = NULL,
                lock_expires_at = NULL,
                status = 'pending',
                verification_result = {_preserved_verification_sql()},
                updated_at = NOW()
            WHERE id = %s
              {owner_clause}
            RETURNING {TASK_COLUMNS}
            """,
            params,
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
            f"""
            WITH expired AS (
                SELECT id, project_id, claimed_by, claimed_at, lock_expires_at
                FROM tasks
                WHERE status = 'running'
                  AND lock_expires_at IS NOT NULL
                  AND lock_expires_at < NOW()
                  AND claimed_by IS NOT NULL
                FOR UPDATE
            ), updated AS (
                UPDATE tasks AS task
                SET claimed_by = NULL,
                    claimed_at = NULL,
                    lock_expires_at = NULL,
                    status = 'pending',
                    verification_result = {_preserved_verification_sql(preserve_closeout=True)},
                    updated_at = NOW()
                FROM expired
                WHERE task.id = expired.id
                RETURNING expired.id, expired.claimed_by, expired.claimed_at,
                          expired.lock_expires_at
            )
            SELECT id, claimed_by, claimed_at, lock_expires_at FROM updated
            """
        )
        reset_claims = cur.fetchall()
        conn.commit()
    if reset_claims:
        from ..events import log_task_event

        for task_id, claimed_by, claimed_at, lock_expires_at in reset_claims:
            try:
                log_task_event(
                    task_id,
                    "Task claim reset after lock expiry",
                    source="summitflow-reset-claims",
                    event_type="task_claim_reset",
                    attributes={
                        "reason": "lock_expired",
                        "claimed_by": claimed_by,
                        "claimed_at": claimed_at.isoformat() if claimed_at else None,
                        "lock_expires_at": lock_expires_at.isoformat() if lock_expires_at else None,
                    },
                )
            except Exception:
                logger.exception("Failed to audit expired claim reset for task %s", task_id)
    return len(reset_claims)


def count_running_tasks(project_id: str, *, exclude_task_id: str | None = None) -> int:
    """Count tasks currently running for a project.

    Returns:
        Number of tasks with status='running' and valid claim.
    """
    params: list[object] = [project_id]
    exclude_clause = ""
    if exclude_task_id:
        exclude_clause = " AND id <> %s"
        params.append(canonicalize_task_id(exclude_task_id))

    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM tasks
            WHERE project_id = %s
              AND status = 'running'
              AND claimed_by IS NOT NULL
              AND (lock_expires_at IS NULL OR lock_expires_at > NOW())
              {exclude_clause}
            """,
            params,
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0
