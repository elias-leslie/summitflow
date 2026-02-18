"""Tasks storage - Row to dict mapping functions.

This module provides functions to convert database rows to task dictionaries.
"""

from __future__ import annotations

from typing import Any

from psycopg.rows import TupleRow

from .columns import EXPECTED_TASK_COLUMNS, EXPECTED_TASK_COLUMNS_WITH_SPIRIT


def row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row to a task dict.

    Column order (40 columns):
        id, project_id, capability_id, title, description, status,
        error_message, branch_name, commits,
        total_sessions, total_tokens_used, created_at, started_at, completed_at,
        priority, task_type, parent_task_id, feature_id,
        claimed_by, claimed_at, lock_expires_at, tier, pre_merge_sha, review_result,
        current_phase, verification_result,
        raw_request, enrichment_status, enriched_by, enriched_at,
        complexity, autonomous,
        qa_status, qa_signoff_at, qa_signoff_by, qa_issues, agent_override,
        agent_hub_session_ids, labels, ai_review
    """
    if row is None:
        raise ValueError("Row cannot be None")
    if len(row) != EXPECTED_TASK_COLUMNS:
        raise ValueError(f"Expected {EXPECTED_TASK_COLUMNS} columns, got {len(row)}")
    return {
        "id": row[0],
        "project_id": row[1],
        "capability_id": row[2],
        "title": row[3],
        "description": row[4],
        "status": row[5],
        "error_message": row[6],
        "branch_name": row[7],
        "commits": row[8] or [],
        "total_sessions": row[9],
        "total_tokens_used": row[10],
        "created_at": row[11],
        "started_at": row[12],
        "completed_at": row[13],
        "priority": row[14],
        "task_type": row[15],
        "parent_task_id": row[16],
        "feature_id": row[17],
        "claimed_by": row[18],
        "claimed_at": row[19],
        "lock_expires_at": row[20],
        "tier": row[21],
        "pre_merge_sha": row[22],
        "review_result": row[23],
        "current_phase": row[24],
        "verification_result": row[25],
        "raw_request": row[26],
        "enrichment_status": row[27],
        "enriched_by": row[28],
        "enriched_at": row[29],
        "complexity": row[30],
        "autonomous": row[31] or False,
        "qa_status": row[32] or "pending",
        "qa_signoff_at": row[33],
        "qa_signoff_by": row[34],
        "qa_issues": row[35] or [],
        "agent_override": row[36],
        "agent_hub_session_ids": row[37] or [],
        "labels": row[38] or [],
        "ai_review": row[39] if row[39] is not None else True,
    }


def row_to_dict_with_spirit(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row with spirit fields to a task dict.

    Column order (46 columns):
        First 40 columns are standard task columns (see row_to_dict).
        Then 6 spirit columns:
        40: objective, 41: spirit_anti, 42: decisions, 43: constraints,
        44: done_when, 45: plan_status
    """
    if row is None:
        raise ValueError("Row cannot be None")
    if len(row) != EXPECTED_TASK_COLUMNS_WITH_SPIRIT:
        raise ValueError(f"Expected {EXPECTED_TASK_COLUMNS_WITH_SPIRIT} columns, got {len(row)}")

    # Build base task dict from first 40 columns
    task = row_to_dict(row[:EXPECTED_TASK_COLUMNS])

    # Add spirit fields (columns 40-45)
    task["objective"] = row[40]
    task["spirit_anti"] = row[41]
    task["decisions"] = row[42] if row[42] else []
    task["constraints"] = row[43] if row[43] else []
    task["done_when"] = row[44] if row[44] else []
    task["plan_status"] = row[45]

    return task
