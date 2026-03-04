"""Tasks storage - Row to dict mapping functions.

This module provides functions to convert database rows to task dictionaries.
"""

from __future__ import annotations

from typing import Any

from psycopg.rows import TupleRow

from .columns import EXPECTED_TASK_COLUMNS, EXPECTED_TASK_COLUMNS_WITH_SPIRIT


def _build_task_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    """Build a task dict from the first 38 columns of a database row."""
    return {
        "id": row[0], "project_id": row[1], "capability_id": row[2],
        "title": row[3], "description": row[4], "status": row[5],
        "error_message": row[6], "branch_name": row[7], "commits": row[8] or [],
        "total_sessions": row[9], "total_tokens_used": row[10],
        "created_at": row[11], "started_at": row[12], "completed_at": row[13],
        "priority": row[14], "task_type": row[15], "parent_task_id": row[16],
        "feature_id": row[17], "claimed_by": row[18], "claimed_at": row[19],
        "lock_expires_at": row[20], "tier": row[21], "pre_merge_sha": row[22],
        "review_result": row[23], "current_phase": row[24],
        "verification_result": row[25], "raw_request": row[26],
        "enrichment_status": row[27], "enriched_by": row[28], "enriched_at": row[29],
        "complexity": row[30], "autonomous": row[31] or False,
        "agent_override": row[32], "agent_hub_session_ids": row[33] or [],
        "labels": row[34] or [], "ai_review": row[35] if row[35] is not None else True,
        "conflict_info": row[36], "merge_sha": row[37],
    }


def row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row to a task dict.

    Column order (38 columns):
        id, project_id, capability_id, title, description, status,
        error_message, branch_name, commits,
        total_sessions, total_tokens_used, created_at, started_at, completed_at,
        priority, task_type, parent_task_id, feature_id,
        claimed_by, claimed_at, lock_expires_at, tier, pre_merge_sha, review_result,
        current_phase, verification_result,
        raw_request, enrichment_status, enriched_by, enriched_at,
        complexity, autonomous,
        agent_override, agent_hub_session_ids, labels, ai_review, conflict_info, merge_sha
    """
    if row is None:
        raise ValueError("Row cannot be None")
    if len(row) != EXPECTED_TASK_COLUMNS:
        raise ValueError(f"Expected {EXPECTED_TASK_COLUMNS} columns, got {len(row)}")
    return _build_task_dict(row)


def row_to_dict_with_spirit(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row with spirit fields to a task dict.

    Column order (44 columns):
        First 38 columns are standard task columns (see row_to_dict).
        Then 6 spirit columns:
        38: objective, 39: spirit_anti, 40: decisions, 41: constraints,
        42: done_when, 43: plan_status
    """
    if row is None:
        raise ValueError("Row cannot be None")
    if len(row) != EXPECTED_TASK_COLUMNS_WITH_SPIRIT:
        raise ValueError(f"Expected {EXPECTED_TASK_COLUMNS_WITH_SPIRIT} columns, got {len(row)}")

    task = _build_task_dict(row[:EXPECTED_TASK_COLUMNS])
    task["objective"] = row[38]
    task["spirit_anti"] = row[39]
    task["decisions"] = row[40] if row[40] else []
    task["constraints"] = row[41] if row[41] else []
    task["done_when"] = row[42] if row[42] else []
    task["plan_status"] = row[43]
    return task


def row_to_dict_with_subtask_summary(row: TupleRow | tuple[Any, ...]) -> dict[str, Any]:
    """Convert a row with spirit fields and subtask counts to a task dict.

    Expects EXPECTED_TASK_COLUMNS_WITH_SPIRIT + 2 columns:
    standard spirit columns followed by subtask_total and subtask_completed.
    """
    expected = EXPECTED_TASK_COLUMNS_WITH_SPIRIT + 2
    if len(row) != expected:
        raise ValueError(f"Expected {expected} columns, got {len(row)}")

    task = row_to_dict_with_spirit(row[:EXPECTED_TASK_COLUMNS_WITH_SPIRIT])
    subtask_total = row[EXPECTED_TASK_COLUMNS_WITH_SPIRIT]
    subtask_completed = row[EXPECTED_TASK_COLUMNS_WITH_SPIRIT + 1]
    progress_percent = (
        round((subtask_completed / subtask_total) * 100, 1) if subtask_total > 0 else 0.0
    )
    task["subtask_summary"] = {
        "total": subtask_total,
        "completed": subtask_completed,
        "next_subtask_id": None,
        "progress_percent": progress_percent,
    }
    return task
