"""Tasks storage - Status transitions and state machine.

Status values: pending, running, paused, completed, failed, cancelled.

Simplified from legacy multi-stage statuses to the lifecycle states used by st.
"""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb

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
        verification_result = CASE WHEN %s = 'completed' THEN verification_result ELSE
            NULLIF(jsonb_strip_nulls(jsonb_build_object(
                'acceptance', CASE WHEN verification_result ? 'acceptance' THEN
                    verification_result->'acceptance' ||
                    '{{"state":"stale","reason":"task_lifecycle_changed_requires_acceptance"}}'::jsonb END,
                'deployment', verification_result->'deployment',
                'live_validation', verification_result->'live_validation',
                'publication_repair', verification_result->'publication_repair'
            )), '{{}}'::jsonb) END,
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
    expected_closeout_request_id: str | None = None,
) -> dict[str, Any] | None:
    """Validate and update status atomically under a row lock."""
    resolved_task_id = canonicalize_task_id(task_id)
    with get_connection() as conn, conn.cursor() as cur:
        if status == "cancelled":
            from .publication_repair import unresolved_repair
            cur.execute("SELECT verification_result, labels FROM tasks WHERE id = %s FOR UPDATE", (resolved_task_id,))
            evidence = cur.fetchone()
            if evidence and unresolved_repair({"verification_result": evidence[0], "labels": evidence[1]}):
                raise ValueError("Cannot cancel unresolved repair findings; resolve them with evidence first")
        if status == "completed":
            from app.services.task_acceptance import completion_gates

            cur.execute(
                """SELECT t.verification_result, ts.context, t.commits, t.project_id, t.labels FROM tasks t
                   LEFT JOIN task_spirit ts ON ts.task_id = t.id
                   WHERE t.id = %s FOR UPDATE OF t""", (resolved_task_id,),
            )
            evidence_row = cur.fetchone()
            if evidence_row:
                gates = completion_gates({"verification_result": evidence_row[0], "context": evidence_row[1],
                                          "commits": evidence_row[2], "id": resolved_task_id, "project_id": evidence_row[3],
                                          "labels": evidence_row[4]}, connection=conn)
                if gates:
                    raise ValueError(f"Task acceptance remains incomplete: {gates}")
        if expected_closeout_request_id is not None:
            cur.execute("SELECT status, verification_result FROM tasks WHERE id = %s FOR UPDATE", (resolved_task_id,))
            current = cur.fetchone()
            intent = ((current[1] or {}).get("closeout") or {}) if current else {}
            if (not current or current[0] not in {"pending", "running", "completed"}
                    or status != "completed" or intent.get("request_id") != expected_closeout_request_id):
                raise ValueError("Completion request was superseded by a task lifecycle change")
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
    *, expected_closeout_request_id: str | None = None,
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
        expected_closeout_request_id=expected_closeout_request_id,
    )


def add_commit(
    task_id: str, commit_sha: str, *, project_id: str | None = None,
    publication: dict[str, Any] | None = None, merge_sha: str | None = None,
) -> dict[str, Any] | None:
    """Add an immutable source once, atomically retaining optional publication evidence.

    Args:
        task_id: Task ID
        commit_sha: Git commit SHA to add

    Returns:
        Updated task dict or None if not found.
    """
    resolved_task_id = canonicalize_task_id(task_id)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""UPDATE tasks SET
                commits = CASE WHEN %s = ANY(COALESCE(commits, ARRAY[]::text[]))
                    THEN commits ELSE array_append(COALESCE(commits, ARRAY[]::text[]), %s) END,
                verification_result = CASE WHEN verification_result IS NULL AND %s::jsonb IS NULL THEN NULL
                ELSE COALESCE(CASE
                    WHEN verification_result ? 'acceptance'
                         AND NOT (%s = ANY(COALESCE(commits, ARRAY[]::text[])))
                         AND verification_result->'acceptance'->>'source_commit' IS DISTINCT FROM %s
                    THEN jsonb_set(verification_result, '{{acceptance}}',
                        verification_result->'acceptance' ||
                        '{{"state":"stale","reason":"new_task_commit_requires_acceptance"}}'::jsonb)
                    ELSE verification_result
                END, '{{}}'::jsonb) || COALESCE(%s::jsonb, '{{}}'::jsonb) END,
                merge_sha = COALESCE(%s, merge_sha), updated_at = NOW()
                WHERE id = %s AND (%s::text IS NULL OR project_id = %s)
                RETURNING {TASK_COLUMNS}""",
            (commit_sha, commit_sha,
             Jsonb({"publication": publication}) if publication is not None else None,
             commit_sha, commit_sha,
             Jsonb({"publication": publication}) if publication is not None else None,
             merge_sha, resolved_task_id, project_id, project_id),
        )
        row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row) if row else None
