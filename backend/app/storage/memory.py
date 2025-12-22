"""Memory storage layer - Observation, Diary, Pattern, and Checkpoint CRUD.

This module provides data access for the Context & Memory Intelligence system.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from .connection import get_connection


# =============================================================================
# Observation Queue Storage
# =============================================================================


def create_queue_item(
    project_id: str,
    session_id: str,
    agent_type: str,
    tool_name: str,
    tool_input: dict[str, Any] | None = None,
    tool_output: str | None = None,
) -> dict[str, Any]:
    """Create a queue item for async observation extraction.

    Returns:
        The created queue item.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO observation_queue
                (project_id, session_id, agent_type, tool_name, tool_input, tool_output)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, project_id, session_id, agent_type, tool_name, tool_input,
                      tool_output, status, created_at, processed_at, error_message, retry_count
            """,
            (project_id, session_id, agent_type, tool_name,
             json.dumps(tool_input) if tool_input else None, tool_output),
        )
        row = cur.fetchone()
        conn.commit()

    return _queue_row_to_dict(row)


def get_pending_queue_items(limit: int = 10) -> list[dict[str, Any]]:
    """Get pending queue items for processing."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, session_id, agent_type, tool_name, tool_input,
                   tool_output, status, created_at, processed_at, error_message, retry_count
            FROM observation_queue
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()

    return [_queue_row_to_dict(row) for row in rows]


def update_queue_item_status(
    item_id: str,
    status: str,
    error_message: str | None = None,
) -> bool:
    """Update queue item status.

    Returns:
        True if updated, False if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        if status == "processed":
            cur.execute(
                """
                UPDATE observation_queue
                SET status = %s, processed_at = NOW(), error_message = %s
                WHERE id = %s
                """,
                (status, error_message, item_id),
            )
        elif status == "failed":
            cur.execute(
                """
                UPDATE observation_queue
                SET status = %s, error_message = %s, retry_count = retry_count + 1
                WHERE id = %s
                """,
                (status, error_message, item_id),
            )
        else:
            cur.execute(
                """
                UPDATE observation_queue
                SET status = %s
                WHERE id = %s
                """,
                (status, item_id),
            )
        updated = cur.rowcount > 0
        conn.commit()

    return updated


def _queue_row_to_dict(row: tuple) -> dict[str, Any]:
    """Convert queue row to dict."""
    return {
        "id": str(row[0]),
        "project_id": row[1],
        "session_id": row[2],
        "agent_type": row[3],
        "tool_name": row[4],
        "tool_input": row[5],
        "tool_output": row[6],
        "status": row[7],
        "created_at": row[8].isoformat() if row[8] else None,
        "processed_at": row[9].isoformat() if row[9] else None,
        "error_message": row[10],
        "retry_count": row[11],
    }


# =============================================================================
# Observations Storage
# =============================================================================


def create_observation(
    project_id: str,
    session_id: str,
    agent_type: str,
    observation_type: str,
    title: str,
    concepts: list[str] | None = None,
    subtitle: str | None = None,
    narrative: str | None = None,
    facts: dict[str, Any] | None = None,
    files_read: list[str] | None = None,
    files_modified: list[str] | None = None,
    tool_name: str | None = None,
    tool_input: dict[str, Any] | None = None,
    discovery_tokens: int = 0,
) -> dict[str, Any]:
    """Create an observation from extracted tool execution data.

    Returns:
        The created observation.
    """
    if concepts is None:
        concepts = []
    if files_read is None:
        files_read = []
    if files_modified is None:
        files_modified = []

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO observations
                (project_id, session_id, agent_type, observation_type, title,
                 concepts, subtitle, narrative, facts, files_read, files_modified,
                 tool_name, tool_input, discovery_tokens)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, project_id, session_id, agent_type, observation_type,
                      concepts, title, subtitle, narrative, facts, files_read,
                      files_modified, tool_name, tool_input, discovery_tokens, created_at
            """,
            (project_id, session_id, agent_type, observation_type, title,
             concepts, subtitle, narrative, json.dumps(facts) if facts else None,
             files_read, files_modified, tool_name,
             json.dumps(tool_input) if tool_input else None, discovery_tokens),
        )
        row = cur.fetchone()
        conn.commit()

    return _observation_row_to_dict(row)


def get_observation(observation_id: str) -> dict[str, Any] | None:
    """Get an observation by ID."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, session_id, agent_type, observation_type,
                   concepts, title, subtitle, narrative, facts, files_read,
                   files_modified, tool_name, tool_input, discovery_tokens, created_at
            FROM observations
            WHERE id = %s
            """,
            (observation_id,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return _observation_row_to_dict(row)


def list_observations(
    project_id: str,
    agent_type: str | None = None,
    observation_type: str | None = None,
    session_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List observations with optional filters."""
    conditions = ["project_id = %s"]
    params: list[Any] = [project_id]

    if agent_type:
        conditions.append("agent_type = %s")
        params.append(agent_type)
    if observation_type:
        conditions.append("observation_type = %s")
        params.append(observation_type)
    if session_id:
        conditions.append("session_id = %s")
        params.append(session_id)

    params.extend([limit, offset])

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, project_id, session_id, agent_type, observation_type,
                   concepts, title, subtitle, narrative, facts, files_read,
                   files_modified, tool_name, tool_input, discovery_tokens, created_at
            FROM observations
            WHERE {" AND ".join(conditions)}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            params,
        )
        rows = cur.fetchall()

    return [_observation_row_to_dict(row) for row in rows]


def search_observations_fts(
    project_id: str,
    query: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Full-text search observations."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, session_id, agent_type, observation_type,
                   concepts, title, subtitle, narrative, facts, files_read,
                   files_modified, tool_name, tool_input, discovery_tokens, created_at,
                   ts_rank(search_vector, plainto_tsquery('english', %s)) AS rank
            FROM observations
            WHERE project_id = %s
              AND search_vector @@ plainto_tsquery('english', %s)
            ORDER BY rank DESC
            LIMIT %s
            """,
            (query, project_id, query, limit),
        )
        rows = cur.fetchall()

    # Exclude rank from result
    return [_observation_row_to_dict(row[:16]) for row in rows]


def _observation_row_to_dict(row: tuple) -> dict[str, Any]:
    """Convert observation row to dict."""
    return {
        "id": str(row[0]),
        "project_id": row[1],
        "session_id": row[2],
        "agent_type": row[3],
        "observation_type": row[4],
        "concepts": row[5] or [],
        "title": row[6],
        "subtitle": row[7],
        "narrative": row[8],
        "facts": row[9],
        "files_read": row[10] or [],
        "files_modified": row[11] or [],
        "tool_name": row[12],
        "tool_input": row[13],
        "discovery_tokens": row[14],
        "created_at": row[15].isoformat() if row[15] else None,
    }


# =============================================================================
# Session Diary Storage
# =============================================================================


def create_diary_entry(
    project_id: str,
    session_id: str,
    agent_type: str,
    outcome: str,
    task_id: str | None = None,
    duration_seconds: int | None = None,
    tokens_used: int | None = None,
    discovery_tokens: int | None = None,
    observation_type: str | None = None,
    concepts: list[str] | None = None,
    what_worked: list[str] | None = None,
    what_failed: list[str] | None = None,
    user_corrections: list[str] | None = None,
    patterns_used: list[str] | None = None,
) -> dict[str, Any]:
    """Create a session diary entry.

    Returns:
        The created diary entry.
    """
    if concepts is None:
        concepts = []

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO session_diary
                (project_id, session_id, task_id, agent_type, duration_seconds,
                 tokens_used, discovery_tokens, outcome, observation_type, concepts,
                 what_worked, what_failed, user_corrections, patterns_used)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, project_id, session_id, task_id, agent_type,
                      duration_seconds, tokens_used, discovery_tokens, outcome,
                      observation_type, concepts, what_worked, what_failed,
                      user_corrections, patterns_used, reflected_at,
                      reflection_notes, patterns_generated, created_at
            """,
            (project_id, session_id, task_id, agent_type, duration_seconds,
             tokens_used, discovery_tokens, outcome, observation_type, concepts,
             json.dumps(what_worked) if what_worked else None,
             json.dumps(what_failed) if what_failed else None,
             json.dumps(user_corrections) if user_corrections else None,
             json.dumps(patterns_used) if patterns_used else None),
        )
        row = cur.fetchone()
        conn.commit()

    return _diary_row_to_dict(row)


def get_diary_entry(entry_id: str) -> dict[str, Any] | None:
    """Get a diary entry by ID.

    Returns:
        The diary entry or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, session_id, task_id, agent_type,
                   duration_seconds, tokens_used, discovery_tokens, outcome,
                   observation_type, concepts, what_worked, what_failed,
                   user_corrections, patterns_used, reflected_at,
                   reflection_notes, patterns_generated, created_at
            FROM session_diary
            WHERE id = %s
            """,
            (entry_id,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return _diary_row_to_dict(row)


def list_diary_entries(
    project_id: str,
    outcome: str | None = None,
    unreflected_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List diary entries with optional filters."""
    conditions = ["project_id = %s"]
    params: list[Any] = [project_id]

    if outcome:
        conditions.append("outcome = %s")
        params.append(outcome)
    if unreflected_only:
        conditions.append("reflected_at IS NULL")

    params.extend([limit, offset])

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, project_id, session_id, task_id, agent_type,
                   duration_seconds, tokens_used, discovery_tokens, outcome,
                   observation_type, concepts, what_worked, what_failed,
                   user_corrections, patterns_used, reflected_at,
                   reflection_notes, patterns_generated, created_at
            FROM session_diary
            WHERE {" AND ".join(conditions)}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            params,
        )
        rows = cur.fetchall()

    return [_diary_row_to_dict(row) for row in rows]


def get_unreflected_diary_count(project_id: str) -> int:
    """Get count of diary entries since last reflection."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM session_diary
            WHERE project_id = %s AND reflected_at IS NULL
            """,
            (project_id,),
        )
        result = cur.fetchone()

    return result[0] if result else 0


def mark_diary_entries_reflected(
    entry_ids: list[str],
    reflection_notes: str | None = None,
    patterns_generated: list[str] | None = None,
) -> int:
    """Mark diary entries as reflected.

    Returns:
        Number of entries updated.
    """
    if not entry_ids:
        return 0

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE session_diary
            SET reflected_at = NOW(),
                reflection_notes = %s,
                patterns_generated = %s
            WHERE id = ANY(%s)
            """,
            (reflection_notes,
             json.dumps(patterns_generated) if patterns_generated else None,
             entry_ids),
        )
        updated = cur.rowcount
        conn.commit()

    return updated


def _diary_row_to_dict(row: tuple) -> dict[str, Any]:
    """Convert diary row to dict."""
    return {
        "id": str(row[0]),
        "project_id": row[1],
        "session_id": row[2],
        "task_id": row[3],
        "agent_type": row[4],
        "duration_seconds": row[5],
        "tokens_used": row[6],
        "discovery_tokens": row[7],
        "outcome": row[8],
        "observation_type": row[9],
        "concepts": row[10] or [],
        "what_worked": row[11],
        "what_failed": row[12],
        "user_corrections": row[13],
        "patterns_used": row[14],
        "reflected_at": row[15].isoformat() if row[15] else None,
        "reflection_notes": row[16],
        "patterns_generated": row[17],
        "created_at": row[18].isoformat() if row[18] else None,
    }


# =============================================================================
# Learned Patterns Storage
# =============================================================================


def create_pattern(
    project_id: str,
    pattern_type: str,
    title: str,
    content: str,
    action: str = "add",
    rationale: str | None = None,
    source_diary_ids: list[str] | None = None,
    source_observation_ids: list[str] | None = None,
    target_pattern_id: str | None = None,
    confidence: float | None = None,
) -> dict[str, Any]:
    """Create a learned pattern.

    Returns:
        The created pattern.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO learned_patterns
                (project_id, pattern_type, title, content, action, rationale,
                 source_diary_ids, source_observation_ids, target_pattern_id, confidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, project_id, pattern_type, title, content, rationale,
                      source_diary_ids, source_observation_ids, action, target_pattern_id,
                      status, confidence, usage_count, last_used_at, superseded_by,
                      applied_to_rules_at, created_at, reviewed_at, reviewed_by
            """,
            (project_id, pattern_type, title, content, action, rationale,
             json.dumps(source_diary_ids) if source_diary_ids else "[]",
             json.dumps(source_observation_ids) if source_observation_ids else "[]",
             target_pattern_id, confidence),
        )
        row = cur.fetchone()
        conn.commit()

    return _pattern_row_to_dict(row)


def get_pattern(pattern_id: str) -> dict[str, Any] | None:
    """Get a pattern by ID."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, pattern_type, title, content, rationale,
                   source_diary_ids, source_observation_ids, action, target_pattern_id,
                   status, confidence, usage_count, last_used_at, superseded_by,
                   applied_to_rules_at, created_at, reviewed_at, reviewed_by
            FROM learned_patterns
            WHERE id = %s
            """,
            (pattern_id,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return _pattern_row_to_dict(row)


def list_patterns(
    project_id: str,
    status: str | None = None,
    action: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List patterns with optional filters."""
    conditions = ["project_id = %s"]
    params: list[Any] = [project_id]

    if status:
        conditions.append("status = %s")
        params.append(status)
    if action:
        conditions.append("action = %s")
        params.append(action)

    params.extend([limit, offset])

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, project_id, pattern_type, title, content, rationale,
                   source_diary_ids, source_observation_ids, action, target_pattern_id,
                   status, confidence, usage_count, last_used_at, superseded_by,
                   applied_to_rules_at, created_at, reviewed_at, reviewed_by
            FROM learned_patterns
            WHERE {" AND ".join(conditions)}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            params,
        )
        rows = cur.fetchall()

    return [_pattern_row_to_dict(row) for row in rows]


def get_stale_patterns(project_id: str, days: int = 30) -> list[dict[str, Any]]:
    """Get patterns that are applied but unused for N days."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, pattern_type, title, content, rationale,
                   source_diary_ids, source_observation_ids, action, target_pattern_id,
                   status, confidence, usage_count, last_used_at, superseded_by,
                   applied_to_rules_at, created_at, reviewed_at, reviewed_by
            FROM learned_patterns
            WHERE project_id = %s
              AND status = 'applied'
              AND (last_used_at IS NULL OR last_used_at < NOW() - INTERVAL '%s days')
            ORDER BY last_used_at ASC NULLS FIRST
            """,
            (project_id, days),
        )
        rows = cur.fetchall()

    return [_pattern_row_to_dict(row) for row in rows]


def update_pattern_status(
    pattern_id: str,
    status: str,
    reviewed_by: str | None = None,
) -> bool:
    """Update pattern status.

    Returns:
        True if updated, False if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE learned_patterns
            SET status = %s, reviewed_at = NOW(), reviewed_by = %s
            WHERE id = %s
            """,
            (status, reviewed_by, pattern_id),
        )
        updated = cur.rowcount > 0
        conn.commit()

    return updated


def mark_pattern_applied(pattern_id: str) -> bool:
    """Mark pattern as applied to rules.

    Returns:
        True if updated, False if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE learned_patterns
            SET status = 'applied', applied_to_rules_at = NOW()
            WHERE id = %s
            """,
            (pattern_id,),
        )
        updated = cur.rowcount > 0
        conn.commit()

    return updated


def increment_pattern_usage(pattern_id: str) -> bool:
    """Increment pattern usage count.

    Returns:
        True if updated, False if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE learned_patterns
            SET usage_count = usage_count + 1, last_used_at = NOW()
            WHERE id = %s
            """,
            (pattern_id,),
        )
        updated = cur.rowcount > 0
        conn.commit()

    return updated


def _pattern_row_to_dict(row: tuple) -> dict[str, Any]:
    """Convert pattern row to dict."""
    confidence = row[11]
    if isinstance(confidence, Decimal):
        confidence = float(confidence)

    return {
        "id": str(row[0]),
        "project_id": row[1],
        "pattern_type": row[2],
        "title": row[3],
        "content": row[4],
        "rationale": row[5],
        "source_diary_ids": row[6],
        "source_observation_ids": row[7],
        "action": row[8],
        "target_pattern_id": str(row[9]) if row[9] else None,
        "status": row[10],
        "confidence": confidence,
        "usage_count": row[12],
        "last_used_at": row[13].isoformat() if row[13] else None,
        "superseded_by": str(row[14]) if row[14] else None,
        "applied_to_rules_at": row[15].isoformat() if row[15] else None,
        "created_at": row[16].isoformat() if row[16] else None,
        "reviewed_at": row[17].isoformat() if row[17] else None,
        "reviewed_by": row[18],
    }


# =============================================================================
# Agent Checkpoints Storage
# =============================================================================


def create_checkpoint(
    project_id: str,
    session_id: str,
    agent_type: str,
    current_action: str | None = None,
    question: str | None = None,
    options: list[dict[str, Any]] | None = None,
    recommendation: str | None = None,
    completed_steps: list[str] | None = None,
    remaining_steps: list[str] | None = None,
    files_modified: list[str] | None = None,
    decisions_made: list[dict[str, Any]] | None = None,
    conversation_summary: str | None = None,
    context_snapshot: dict[str, Any] | None = None,
    tokens_used: int | None = None,
) -> dict[str, Any]:
    """Create an agent checkpoint.

    Returns:
        The created checkpoint.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_checkpoints
                (project_id, session_id, agent_type, current_action, question,
                 options, recommendation, completed_steps, remaining_steps,
                 files_modified, decisions_made, conversation_summary,
                 context_snapshot, tokens_used)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, project_id, session_id, agent_type, current_action,
                      question, options, recommendation, completed_steps,
                      remaining_steps, files_modified, decisions_made,
                      conversation_summary, context_snapshot, tokens_used, created_at
            """,
            (project_id, session_id, agent_type, current_action, question,
             json.dumps(options) if options else None, recommendation,
             json.dumps(completed_steps) if completed_steps else None,
             json.dumps(remaining_steps) if remaining_steps else None,
             json.dumps(files_modified) if files_modified else None,
             json.dumps(decisions_made) if decisions_made else None,
             conversation_summary,
             json.dumps(context_snapshot) if context_snapshot else None,
             tokens_used),
        )
        row = cur.fetchone()
        conn.commit()

    return _checkpoint_row_to_dict(row)


def get_latest_checkpoint(session_id: str) -> dict[str, Any] | None:
    """Get the most recent checkpoint for a session."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, session_id, agent_type, current_action,
                   question, options, recommendation, completed_steps,
                   remaining_steps, files_modified, decisions_made,
                   conversation_summary, context_snapshot, tokens_used, created_at
            FROM agent_checkpoints
            WHERE session_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (session_id,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return _checkpoint_row_to_dict(row)


def list_checkpoints(
    project_id: str,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List checkpoints for a project."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, session_id, agent_type, current_action,
                   question, options, recommendation, completed_steps,
                   remaining_steps, files_modified, decisions_made,
                   conversation_summary, context_snapshot, tokens_used, created_at
            FROM agent_checkpoints
            WHERE project_id = %s
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            (project_id, limit, offset),
        )
        rows = cur.fetchall()

    return [_checkpoint_row_to_dict(row) for row in rows]


def delete_checkpoint(checkpoint_id: str) -> bool:
    """Delete a checkpoint.

    Returns:
        True if deleted, False if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM agent_checkpoints WHERE id = %s",
            (checkpoint_id,),
        )
        deleted = cur.rowcount > 0
        conn.commit()

    return deleted


def _checkpoint_row_to_dict(row: tuple) -> dict[str, Any]:
    """Convert checkpoint row to dict."""
    return {
        "id": str(row[0]),
        "project_id": row[1],
        "session_id": row[2],
        "agent_type": row[3],
        "current_action": row[4],
        "question": row[5],
        "options": row[6],
        "recommendation": row[7],
        "completed_steps": row[8],
        "remaining_steps": row[9],
        "files_modified": row[10],
        "decisions_made": row[11],
        "conversation_summary": row[12],
        "context_snapshot": row[13],
        "tokens_used": row[14],
        "created_at": row[15].isoformat() if row[15] else None,
    }
