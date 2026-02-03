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
# Note: Migration 072 dropped: plan_content, labels, objective, spirit_anti,
#       decisions, constraints, done_when (moved to task_spirit/task_labels)
# Note: Migration 099 dropped: progress_log (moved to events table)
# Note: Migration 101 added: agent_override
# Note: Migration 028147425749 added: agent_hub_session_ids
TASK_COLUMNS = """id, project_id, capability_id, title, description, status,
    error_message, branch_name, commits, pull_request_url,
    total_sessions, total_tokens_used, created_at, started_at, completed_at,
    priority, task_type, parent_task_id, feature_id,
    claimed_by, claimed_at, lock_expires_at, tier, pre_merge_sha, review_result,
    current_phase, verification_result,
    raw_request, enrichment_status, enriched_by, enriched_at,
    complexity, autonomous,
    qa_status, qa_signoff_at, qa_signoff_by, qa_issues, agent_override, agent_hub_session_ids"""

# Aliased version for JOINs (prefixed with t.)
TASK_COLUMNS_ALIASED = """t.id, t.project_id, t.capability_id, t.title, t.description, t.status,
    t.error_message, t.branch_name, t.commits, t.pull_request_url,
    t.total_sessions, t.total_tokens_used, t.created_at, t.started_at, t.completed_at,
    t.priority, t.task_type, t.parent_task_id, t.feature_id,
    t.claimed_by, t.claimed_at, t.lock_expires_at, t.tier, t.pre_merge_sha, t.review_result,
    t.current_phase, t.verification_result,
    t.raw_request, t.enrichment_status, t.enriched_by, t.enriched_at,
    t.complexity, t.autonomous,
    t.qa_status, t.qa_signoff_at, t.qa_signoff_by, t.qa_issues, t.agent_override, t.agent_hub_session_ids"""

EXPECTED_TASK_COLUMNS = 39

# Columns for queries that JOIN with task_spirit (45 columns total)
# Adds 6 spirit fields: objective, spirit_anti, decisions, constraints, done_when, plan_status
TASK_COLUMNS_WITH_SPIRIT = """t.id, t.project_id, t.capability_id, t.title, t.description, t.status,
    t.error_message, t.branch_name, t.commits, t.pull_request_url,
    t.total_sessions, t.total_tokens_used, t.created_at, t.started_at, t.completed_at,
    t.priority, t.task_type, t.parent_task_id, t.feature_id,
    t.claimed_by, t.claimed_at, t.lock_expires_at, t.tier, t.pre_merge_sha, t.review_result,
    t.current_phase, t.verification_result,
    t.raw_request, t.enrichment_status, t.enriched_by, t.enriched_at,
    t.complexity, t.autonomous,
    t.qa_status, t.qa_signoff_at, t.qa_signoff_by, t.qa_issues, t.agent_override, t.agent_hub_session_ids,
    ts.objective, ts.spirit_anti, ts.decisions, ts.constraints, ts.done_when, ts.plan_status"""

EXPECTED_TASK_COLUMNS_WITH_SPIRIT = 45


def _generate_task_id() -> str:
    """Generate a unique task ID."""
    return generate_prefixed_id("task")


def _row_to_dict_with_spirit(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row with spirit fields to a task dict.

    Column order (45 columns):
        First 39 columns are standard task columns (see _row_to_dict).
        Then 6 spirit columns:
        39: objective, 40: spirit_anti, 41: decisions, 42: constraints,
        43: done_when, 44: plan_status
    """
    if row is None:
        raise ValueError("Row cannot be None")
    if len(row) != EXPECTED_TASK_COLUMNS_WITH_SPIRIT:
        raise ValueError(f"Expected {EXPECTED_TASK_COLUMNS_WITH_SPIRIT} columns, got {len(row)}")

    # Build base task dict from first 39 columns
    task = _row_to_dict(row[:EXPECTED_TASK_COLUMNS])

    # Add spirit fields (columns 39-44)
    task["objective"] = row[39]
    task["spirit_anti"] = row[40]
    task["decisions"] = row[41] if row[41] else []
    task["constraints"] = row[42] if row[42] else []
    task["done_when"] = row[43] if row[43] else []
    task["plan_status"] = row[44]

    return task


def _row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert a database row to a task dict.

    Column order (39 columns):
        id, project_id, capability_id, title, description, status,
        error_message, branch_name, commits, pull_request_url,
        total_sessions, total_tokens_used, created_at, started_at, completed_at,
        priority, task_type, parent_task_id, feature_id,
        claimed_by, claimed_at, lock_expires_at, tier, pre_merge_sha, review_result,
        current_phase, verification_result,
        raw_request, enrichment_status, enriched_by, enriched_at,
        complexity, autonomous,
        qa_status, qa_signoff_at, qa_signoff_by, qa_issues, agent_override, agent_hub_session_ids

    Note: Migration 072 dropped plan_content, labels, objective, spirit_anti,
          decisions, constraints, done_when (now in task_spirit/task_labels)
    Note: Migration 099 dropped progress_log (now in events table)
    Note: Migration 101 added agent_override
    Note: Migration 028147425749 added agent_hub_session_ids
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
    }


def create_task(
    project_id: str,
    title: str,
    capability_id: int | None = None,
    description: str | None = None,
    task_id: str | None = None,
    priority: int = 2,
    task_type: str = "task",
    parent_task_id: str | None = None,
    tier: int | None = None,
    current_phase: str = "plan",
    raw_request: str | None = None,
    enrichment_status: str = "none",
    complexity: str | None = None,
    autonomous: bool = False,
) -> dict[str, Any]:
    """Create a new task.

    Args:
        project_id: Project ID
        title: Task title
        capability_id: Optional capability database ID to link to (TDD)
        description: Optional task description
        task_id: Optional custom task ID (auto-generated if not provided)
        priority: Priority 0-4 (0=critical, 4=backlog), default 2
        task_type: Type: 'task', 'bug', 'chore'
        parent_task_id: Parent task ID for subtasks
        tier: Execution tier 1-4 for autonomous execution (defaults to 2)
        current_phase: Task phase: plan, implement, test, verify, complete
        raw_request: Original user input before AI enrichment
        enrichment_status: Enrichment state: none, draft, enriching, review, discussing, accepted, failed
        complexity: Task complexity tier (SIMPLE, STANDARD, COMPLEX)
        autonomous: Enable autonomous execution (Flash/Opus pipeline)

    Note:
        - objective, spirit_anti, decisions, constraints, done_when are stored
          in task_spirit table. Use storage.task_spirit functions.
        - labels are stored in task_labels table. Use storage.task_labels functions.
        - Verification happens at step level via verify_command. See storage.steps.

    Returns:
        The created task dict with all columns.
    """
    if task_id is None:
        task_id = _generate_task_id()
    # Auto-enable autonomous for mechanical task types (opt-in by default)
    if not autonomous and task_type in ("refactor", "debt", "regression"):
        autonomous = True

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO tasks (id, project_id, capability_id, title, description,
                               priority, task_type, parent_task_id, tier,
                               current_phase, raw_request, enrichment_status,
                               complexity, autonomous)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING {TASK_COLUMNS}
            """,
            (
                task_id,
                project_id,
                capability_id,
                title,
                description,
                priority,
                task_type,
                parent_task_id,
                tier,
                current_phase,
                raw_request,
                enrichment_status,
                complexity,
                autonomous,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    return _row_to_dict(row)


def get_task(task_id: str) -> dict[str, Any] | None:
    """Get a task by ID with spirit fields.

    Returns:
        Task dict with spirit fields (objective, spirit_anti, decisions,
        constraints, done_when, plan_status) or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {TASK_COLUMNS_WITH_SPIRIT}
            FROM tasks t
            LEFT JOIN task_spirit ts ON t.id = ts.task_id
            WHERE t.id = %s
            """,
            (task_id,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return _row_to_dict_with_spirit(row)


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

    # Note: objective, spirit_anti, decisions, constraints, done_when, labels
    # are now in task_spirit/task_labels tables (migration 072)
    # Note: progress_log moved to events table (migration 099)
    # Note: agent_override added in migration 101
    allowed_fields = {
        "project_id",  # Allow moving task between projects
        "title",
        "description",
        "status",
        "error_message",
        "branch_name",
        "commits",
        "pull_request_url",
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
        "autonomous",
        "qa_status",
        "qa_signoff_at",
        "qa_signoff_by",
        "qa_issues",
        "agent_override",
        "agent_hub_session_ids",
    }

    invalid = set(fields.keys()) - allowed_fields
    if invalid:
        raise ValueError(f"Invalid fields: {invalid}")

    set_clauses: list[sql.Composable] = []
    params: list[Any] = []
    # JSONB dict fields
    jsonb_dict_fields = {"review_result", "verification_result"}
    # JSONB list fields
    jsonb_list_fields = {"qa_issues"}
    for field, value in fields.items():
        if field in ("commits", "labels", "agent_hub_session_ids") and isinstance(value, list):
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


def add_agent_hub_session(task_id: str, session_id: str) -> dict[str, Any] | None:
    """Add an Agent Hub session ID to a task.

    Appends the session_id to the agent_hub_session_ids array if not already present.
    This links the task to Agent Hub sessions for full observability.

    Args:
        task_id: Task ID
        session_id: Agent Hub session ID to add

    Returns:
        Updated task dict or None if task not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE tasks
            SET agent_hub_session_ids = array_append(
                COALESCE(agent_hub_session_ids, ARRAY[]::TEXT[]),
                %s
            )
            WHERE id = %s
            AND NOT (%s = ANY(COALESCE(agent_hub_session_ids, ARRAY[]::TEXT[])))
            RETURNING {TASK_COLUMNS}
            """,
            (session_id, task_id, session_id),
        )
        row = cur.fetchone()
        conn.commit()

    # If no row returned, either task not found or session_id already exists
    # Try to fetch the task to distinguish
    if not row:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {TASK_COLUMNS} FROM tasks WHERE id = %s",
                (task_id,),
            )
            row = cur.fetchone()

    if not row:
        return None
    return _row_to_dict(row)


def get_agent_hub_sessions(task_id: str) -> list[str]:
    """Get Agent Hub session IDs for a task.

    Args:
        task_id: Task ID

    Returns:
        List of Agent Hub session IDs (empty if task not found or no sessions).
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT agent_hub_session_ids FROM tasks WHERE id = %s",
            (task_id,),
        )
        row = cur.fetchone()

    if not row or not row[0]:
        return []
    return list(row[0])
