"""Internal plan workflow operations for task_spirit storage - approve, reject."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from ._task_spirit_helpers import _row_to_dict
from .connection import get_connection

logger = logging.getLogger(__name__)


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
            """
            UPDATE task_spirit SET
                plan_status = 'approved',
                plan_approved_at = %s,
                plan_approved_by = %s,
                plan_history = plan_history || %s::jsonb
            WHERE task_id = %s
            RETURNING *
            """,
            (now, approved_by, json.dumps([history_entry]), task_id),
        )
        row = cur.fetchone()
        conn.commit()
    if row:
        logger.info(f"Approved plan for task {task_id} by {approved_by}")
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
            """
            UPDATE task_spirit SET
                plan_status = 'rejected',
                plan_history = plan_history || %s::jsonb
            WHERE task_id = %s
            RETURNING *
            """,
            (json.dumps([history_entry]), task_id),
        )
        row = cur.fetchone()
        conn.commit()
    if row:
        logger.info(f"Rejected plan for task {task_id} by {rejected_by}: {reason}")
    return _row_to_dict(row)
