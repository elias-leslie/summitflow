"""Tasks storage - Update operations.

This module provides functions to update task fields.
"""

from __future__ import annotations

import json
from typing import Any

from psycopg import sql

from ..connection import get_connection
from .columns import TASK_COLUMNS
from .mapping import row_to_dict

# Allowed fields for task updates
# Note: objective, spirit_anti, decisions, constraints, done_when
# are in task_spirit table (migration 072)
# Note: progress_log moved to events table (migration 099)
# Note: agent_override added in migration 101
ALLOWED_UPDATE_FIELDS = {
    "project_id",  # Allow moving task between projects
    "title",
    "description",
    "status",
    "error_message",
    "branch_name",
    "commits",
    "total_sessions",
    "total_tokens_used",
    "started_at",
    "completed_at",
    "priority",
    "task_type",
    "parent_task_id",
    "capability_id",
    "feature_id",
    "claimed_by",
    "claimed_at",
    "lock_expires_at",
    "tier",
    "pre_merge_sha",
    "review_result",
    "current_phase",
    "verification_result",
    "raw_request",
    "enrichment_status",
    "enriched_by",
    "enriched_at",
    "complexity",
    "execution_mode",
    "autonomous",
    "agent_override",
    "agent_hub_session_ids",
    "labels",
    "ai_review",
    "conflict_info",
    "merge_sha",
    "updated_at",
}

# JSONB dict fields
JSONB_DICT_FIELDS = {"review_result", "verification_result", "conflict_info"}

# JSONB list fields
JSONB_LIST_FIELDS: set[str] = set()


def _build_set_clauses(
    fields: dict[str, Any],
) -> tuple[list[sql.Composable], list[Any]]:
    """Build SQL SET clauses and parameters from a field dict.

    Args:
        fields: Mapping of column name to value.

    Returns:
        A tuple of (set_clauses, params).
    """
    set_clauses: list[sql.Composable] = []
    params: list[Any] = []

    for field, value in fields.items():
        if isinstance(value, sql.Composable):
            set_clauses.append(sql.SQL("{} = {}").format(sql.Identifier(field), value))
            continue
        if field in ("commits", "labels", "agent_hub_session_ids") and isinstance(value, list):
            set_clauses.append(sql.SQL("{} = %s").format(sql.Identifier(field)))
            params.append(value)
        elif (field in JSONB_DICT_FIELDS and isinstance(value, dict)) or (
            field in JSONB_LIST_FIELDS and isinstance(value, list)
        ):
            set_clauses.append(sql.SQL("{} = %s::jsonb").format(sql.Identifier(field)))
            params.append(json.dumps(value))
        else:
            set_clauses.append(sql.SQL("{} = %s").format(sql.Identifier(field)))
            params.append(value)

    return set_clauses, params


def update_task_fields(task_id: str, **fields: Any) -> dict[str, Any] | None:
    """Update task fields.

    Args:
        task_id: Task ID
        **fields: Fields to update (e.g., title='New title', description='...')

    Returns:
        Updated task dict or None if not found.

    Raises:
        ValueError: If no fields provided or invalid field name.
    """
    if not fields:
        raise ValueError("No fields provided to update")

    invalid = set(fields.keys()) - ALLOWED_UPDATE_FIELDS
    if invalid:
        raise ValueError(f"Invalid fields: {invalid}")

    if "updated_at" not in fields:
        fields["updated_at"] = sql.SQL("NOW()")

    set_clauses, params = _build_set_clauses(fields)
    params.append(task_id)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL(f"""
            UPDATE tasks
            SET {{set_clause}}
            WHERE id = %s
            RETURNING {TASK_COLUMNS}
            """).format(set_clause=sql.SQL(", ").join(set_clauses)),
            tuple(params),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        return None
    return row_to_dict(row)
