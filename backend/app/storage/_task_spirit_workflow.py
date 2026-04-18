"""Internal plan workflow operations for task_spirit storage - approve, reject, status sync."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from psycopg import sql

from ..logging_config import get_logger
from ._sql import static_sql
from ._task_spirit_helpers import SPIRIT_SELECT, _row_to_dict
from .connection import get_connection

logger = get_logger(__name__)


def approve_plan(
    task_id: str,
    approved_by: str = "user",
    notes: str | None = None,
) -> dict[str, Any] | None:
    """Approve a task's plan, allowing execution to start.

    Args:
        task_id: The task ID
        approved_by: Who/what approved the plan
        notes: Optional approval notes

    Returns:
        Updated record or None if not found
    """
    now = datetime.now(UTC)
    history_entry = {
        "status": "approved",
        "timestamp": now.isoformat(),
        "actor": approved_by,
        "notes": notes,
    }
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            sql.SQL(
                """
            UPDATE task_spirit SET
                plan_status = 'approved',
                plan_approved_at = %s,
                plan_approved_by = %s,
                plan_history = COALESCE(plan_history, '[]'::jsonb) || %s::jsonb,
                updated_at = NOW()
            WHERE task_id = %s
            RETURNING {returning}
            """
            ).format(returning=static_sql(SPIRIT_SELECT)),
            (now, approved_by, json.dumps([history_entry]), task_id),
        )
        row = cur.fetchone()
        conn.commit()
    if row:
        logger.info("Approved plan for task %s by %s", task_id, approved_by)
    return _row_to_dict(row)


def reject_plan(
    task_id: str,
    rejected_by: str = "user",
    reason: str | None = None,
) -> dict[str, Any] | None:
    """Reject a task's plan, requiring revision.

    Args:
        task_id: The task ID
        rejected_by: Who/what rejected the plan
        reason: Reason for rejection

    Returns:
        Updated record or None if not found
    """
    now = datetime.now(UTC)
    history_entry = {
        "status": "rejected",
        "timestamp": now.isoformat(),
        "actor": rejected_by,
        "reason": reason,
    }
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            sql.SQL(
                """
            UPDATE task_spirit SET
                plan_status = 'rejected',
                plan_history = COALESCE(plan_history, '[]'::jsonb) || %s::jsonb,
                updated_at = NOW()
            WHERE task_id = %s
            RETURNING {returning}
            """
            ).format(returning=static_sql(SPIRIT_SELECT)),
            (json.dumps([history_entry]), task_id),
        )
        row = cur.fetchone()
        conn.commit()
    if row:
        logger.info("Rejected plan for task %s by %s: %s", task_id, rejected_by, reason)
    return _row_to_dict(row)


def set_plan_status(
    task_id: str,
    plan_status: str,
    notes: str | None = None,
    actor: str = "system",
) -> dict[str, Any] | None:
    """Set plan status directly and reset approval metadata unless approved elsewhere."""
    now = datetime.now(UTC)
    history_entry = {
        "status": plan_status,
        "timestamp": now.isoformat(),
        "actor": actor,
        "notes": notes,
    }
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            sql.SQL(
                """
            UPDATE task_spirit SET
                plan_status = %s,
                plan_approved_at = CASE WHEN %s = 'approved' THEN COALESCE(plan_approved_at, %s) ELSE NULL END,
                plan_approved_by = CASE WHEN %s = 'approved' THEN COALESCE(plan_approved_by, %s) ELSE NULL END,
                plan_history = COALESCE(plan_history, '[]'::jsonb) || %s::jsonb,
                updated_at = NOW()
            WHERE task_id = %s
            RETURNING {returning}
            """
            ).format(returning=static_sql(SPIRIT_SELECT)),
            (plan_status, plan_status, now, plan_status, actor, json.dumps([history_entry]), task_id),
        )
        row = cur.fetchone()
        conn.commit()
    if row:
        logger.info("Set plan status for task %s to %s", task_id, plan_status)
    return _row_to_dict(row)
