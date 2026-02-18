"""Tasks storage - Row to dict mapping functions.

This module provides functions to convert database rows to task dictionaries.
"""

from __future__ import annotations

from typing import Any

from psycopg.rows import TupleRow

from .columns import EXPECTED_TASK_COLUMNS, EXPECTED_TASK_COLUMNS_WITH_SPIRIT


def row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row to a task dict.

    Column order (41 columns):
        id, project_id, capability_id, title, description, status,
        error_message, branch_name, commits, pull_request_url,
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
        "pull_request_url": row[9],
        "total_sessions": row[10],
        "total_tokens_used": row[11],
        "created_at": row[12],
        "started_at": row[13],
        "completed_at": row[14],
        "priority": row[15],
        "task_type": row[16],
        "parent_task_id": row[17],
        "feature_id": row[18],
        "claimed_by": row[19],
        "claimed_at": row[20],
        "lock_expires_at": row[21],
        "tier": row[22],
        "pre_merge_sha": row[23],
        "review_result": row[24],
        "current_phase": row[25],
        "verification_result": row[26],
        "raw_request": row[27],
        "enrichment_status": row[28],
        "enriched_by": row[29],
        "enriched_at": row[30],
        "complexity": row[31],
        "autonomous": row[32] or False,
        "qa_status": row[33] or "pending",
        "qa_signoff_at": row[34],
        "qa_signoff_by": row[35],
        "qa_issues": row[36] or [],
        "agent_override": row[37],
        "agent_hub_session_ids": row[38] or [],
        "labels": row[39] or [],
        "ai_review": row[40] if row[40] is not None else True,
    }


def row_to_dict_with_spirit(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row with spirit fields to a task dict.

    Column order (47 columns):
        First 41 columns are standard task columns (see row_to_dict).
        Then 6 spirit columns:
        41: objective, 42: spirit_anti, 43: decisions, 44: constraints,
        45: done_when, 46: plan_status
    """
    if row is None:
        raise ValueError("Row cannot be None")
    if len(row) != EXPECTED_TASK_COLUMNS_WITH_SPIRIT:
        raise ValueError(f"Expected {EXPECTED_TASK_COLUMNS_WITH_SPIRIT} columns, got {len(row)}")

    # Build base task dict from first 40 columns
    task = row_to_dict(row[:EXPECTED_TASK_COLUMNS])

    # Add spirit fields (columns 41-46)
    task["objective"] = row[41]
    task["spirit_anti"] = row[42]
    task["decisions"] = row[43] if row[43] else []
    task["constraints"] = row[44] if row[44] else []
    task["done_when"] = row[45] if row[45] else []
    task["plan_status"] = row[46]

    return task
