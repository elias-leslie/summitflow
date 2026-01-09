"""Tasks storage - Core CRUD operations and row mapping.

This module provides basic data access for task records.
"""

from __future__ import annotations

import json
from typing import Any

from psycopg import sql
from psycopg.rows import TupleRow

from ..connection import generate_prefixed_id, get_connection

# Column list for all task SELECT/RETURNING queries (39 columns)
# Order must match _row_to_dict index mapping
# Note: spec_content and current_criterion_id dropped in migration 038
# DEPRECATED: plan_content column kept for backward compatibility, but tasks should use
# normalized task_subtasks and task_subtask_steps tables instead. See migration 039.
TASK_COLUMNS = """id, project_id, capability_id, title, description, status,
    plan_content, progress_log,
    error_message, branch_name, commits, pull_request_url,
    total_sessions, total_tokens_used, created_at, started_at, completed_at,
    priority, labels, task_type, parent_task_id,
    claimed_by, claimed_at, lock_expires_at, tier, pre_merge_sha, review_result,
    objective, current_phase, verification_result,
    raw_request, enrichment_status, enriched_by, enriched_at,
    spirit_anti, decisions, constraints, done_when, complexity"""

# Aliased version for JOINs (prefixed with t.)
TASK_COLUMNS_ALIASED = """t.id, t.project_id, t.capability_id, t.title, t.description, t.status,
    t.plan_content, t.progress_log,
    t.error_message, t.branch_name, t.commits, t.pull_request_url,
    t.total_sessions, t.total_tokens_used, t.created_at, t.started_at, t.completed_at,
    t.priority, t.labels, t.task_type, t.parent_task_id,
    t.claimed_by, t.claimed_at, t.lock_expires_at, t.tier, t.pre_merge_sha, t.review_result,
    t.objective, t.current_phase, t.verification_result,
    t.raw_request, t.enrichment_status, t.enriched_by, t.enriched_at,
    t.spirit_anti, t.decisions, t.constraints, t.done_when, t.complexity"""

EXPECTED_TASK_COLUMNS = 39


def _generate_task_id() -> str:
    """Generate a unique task ID."""
    return generate_prefixed_id("task")


def _row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row to a task dict.

    Column order (39 columns):
        id, project_id, capability_id, title, description, status,
        plan_content, progress_log,
        error_message, branch_name, commits, pull_request_url,
        total_sessions, total_tokens_used, created_at, started_at, completed_at,
        priority, labels, task_type, parent_task_id,
        claimed_by, claimed_at, lock_expires_at, tier, pre_merge_sha, review_result,
        objective, current_phase, verification_result,
        raw_request, enrichment_status, enriched_by, enriched_at,
        spirit_anti, decisions, constraints, done_when, complexity

    Note: spec_content and current_criterion_id dropped in migration 038
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
        "plan_content": row[6],
        "progress_log": row[7],
        "error_message": row[8],
        "branch_name": row[9],
        "commits": row[10] or [],
        "pull_request_url": row[11],
        "total_sessions": row[12],
        "total_tokens_used": row[13],
        "created_at": row[14],
        "started_at": row[15],
        "completed_at": row[16],
        # Issue tracking fields
        "priority": row[17],
        "labels": row[18] or [],
        "task_type": row[19],
        "parent_task_id": row[20],
        # Autonomous execution fields
        "claimed_by": row[21],
        "claimed_at": row[22],
        "lock_expires_at": row[23],
        "tier": row[24],
        "pre_merge_sha": row[25],
        "review_result": row[26],
        # AI agent reliability fields
        "objective": row[27],
        "current_phase": row[28],
        "verification_result": row[29],
        # AI enrichment fields
        "raw_request": row[30],
        "enrichment_status": row[31],
        "enriched_by": row[32],
        "enriched_at": row[33],
        # Pipeline v2 fields
        "spirit_anti": row[34],
        "decisions": row[35],
        "constraints": row[36],
        "done_when": row[37],
        "complexity": row[38],
    }


def create_task(
    project_id: str,
    title: str,
    capability_id: int | None = None,
    description: str | None = None,
    task_id: str | None = None,
    priority: int = 2,
    labels: list[str] | None = None,
    task_type: str = "task",
    parent_task_id: str | None = None,
    tier: int | None = None,
    objective: str | None = None,
    current_phase: str = "plan",
    raw_request: str | None = None,
    enrichment_status: str = "none",
    # Pipeline v2 fields
    spirit_anti: str | None = None,
    decisions: list[dict[str, Any]] | None = None,
    constraints: list[str] | None = None,
    done_when: list[str] | None = None,
    complexity: str | None = None,
) -> dict[str, Any]:
    """Create a new task.

    Args:
        project_id: Project ID
        title: Task title
        capability_id: Optional capability database ID to link to (TDD)
        description: Optional task description
        task_id: Optional custom task ID (auto-generated if not provided)
        priority: Priority 0-4 (0=critical, 4=backlog), default 2
        labels: List of labels (complexity:small, domains:backend, etc.)
        task_type: Type: 'task', 'bug', 'chore'
        parent_task_id: Parent task ID for subtasks
        tier: Execution tier 1-4 for autonomous execution (defaults to 2)
        objective: Single measurable goal statement
        current_phase: Task phase: plan, implement, test, verify, complete
        raw_request: Original user input before AI enrichment
        enrichment_status: Enrichment state: none, draft, enriching, review, discussing, accepted, failed
        spirit_anti: What NOT to do - failure mode to avoid
        decisions: Implementation decisions made during planning
        constraints: Boundaries that must not be crossed
        done_when: Checklist of completion conditions
        complexity: Task complexity tier (SIMPLE, STANDARD, COMPLEX)

    Note:
        Acceptance criteria are now managed via task_criteria junction table.
        Use storage.criteria.link_criterion_to_task() to add criteria.

    Returns:
        The created task dict with all columns.
    """
    if task_id is None:
        task_id = _generate_task_id()
    if labels is None:
        labels = []

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO tasks (id, project_id, capability_id, title, description,
                               priority, labels, task_type, parent_task_id, tier,
                               objective, current_phase, raw_request, enrichment_status,
                               spirit_anti, decisions, constraints, done_when, complexity)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s)
            RETURNING {TASK_COLUMNS}
            """,
            (
                task_id,
                project_id,
                capability_id,
                title,
                description,
                priority,
                labels,
                task_type,
                parent_task_id,
                tier,
                objective,
                current_phase,
                raw_request,
                enrichment_status,
                spirit_anti,
                json.dumps(decisions) if decisions else None,
                json.dumps(constraints) if constraints else None,
                json.dumps(done_when) if done_when else None,
                complexity,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row)


def get_task(task_id: str) -> dict[str, Any] | None:
    """Get a task by ID.

    Returns:
        Task dict or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {TASK_COLUMNS}
            FROM tasks
            WHERE id = %s
            """,
            (task_id,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return _row_to_dict(row)


def update_task(task_id: str, **fields: Any) -> dict[str, Any] | None:
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

    allowed_fields = {
        "project_id",  # Allow moving task between projects
        "title",
        "description",
        "status",
        "plan_content",
        "progress_log",
        "error_message",
        "branch_name",
        "commits",
        "pull_request_url",
        "total_sessions",
        "total_tokens_used",
        "started_at",
        "completed_at",
        # Issue tracking fields
        "priority",
        "labels",
        "task_type",
        "parent_task_id",
        # TDD linkage
        "capability_id",
        # Autonomous execution fields
        "claimed_by",
        "claimed_at",
        "lock_expires_at",
        "tier",
        "pre_merge_sha",
        "review_result",
        # AI agent reliability fields
        "objective",
        "current_phase",
        "verification_result",
        # AI enrichment fields
        "raw_request",
        "enrichment_status",
        "enriched_by",
        "enriched_at",
        # Pipeline v2 fields
        "spirit_anti",
        "decisions",
        "constraints",
        "done_when",
        "complexity",
    }

    invalid = set(fields.keys()) - allowed_fields
    if invalid:
        raise ValueError(f"Invalid fields: {invalid}")

    set_clauses: list[sql.Composable] = []
    params: list[Any] = []
    # JSONB dict fields
    jsonb_dict_fields = {"plan_content", "review_result", "verification_result"}
    # JSONB list fields (Pipeline v2)
    jsonb_list_fields = {"decisions", "constraints", "done_when"}
    for field, value in fields.items():
        if field in ("commits", "labels") and isinstance(value, list):
            set_clauses.append(sql.SQL("{} = %s").format(sql.Identifier(field)))
            params.append(value)
        elif (field in jsonb_dict_fields and isinstance(value, dict)) or (
            field in jsonb_list_fields and isinstance(value, list)
        ):
            set_clauses.append(sql.SQL("{} = %s::jsonb").format(sql.Identifier(field)))
            params.append(json.dumps(value))
        else:
            set_clauses.append(sql.SQL("{} = %s").format(sql.Identifier(field)))
            params.append(value)

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
    return _row_to_dict(row)


def delete_task(task_id: str) -> bool:
    """Delete a task.

    Returns:
        True if deleted, False if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM tasks WHERE id = %s RETURNING id",
            (task_id,),
        )
        result = cur.fetchone()
        conn.commit()

    return result is not None
