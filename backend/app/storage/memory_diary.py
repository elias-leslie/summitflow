"""Memory diary storage - Session diary management.

This module handles the session_diary table operations.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from psycopg import sql
from psycopg.rows import TupleRow

from .agent_configs import is_memory_feature_enabled
from .connection import get_connection

logger = logging.getLogger(__name__)

# Column list for DRY queries
DIARY_COLUMNS = """
    id, project_id, session_id, task_id, agent_type,
    duration_seconds, tokens_used, discovery_tokens, outcome,
    observation_type, concepts, what_worked, what_failed,
    user_corrections, patterns_used, reflected_at,
    reflection_notes, patterns_generated, created_at
""".strip()


def _json_or_default(obj: Any, default: str | None = None) -> str | None:
    """Serialize object to JSON or return default if falsy."""
    return json.dumps(obj) if obj else default


def _build_where_clause(
    filters: dict[str, Any],
    special_conditions: list[str] | None = None,
) -> tuple[sql.SQL | sql.Composed, list[Any]]:
    """Build a WHERE clause from filters dict."""
    conditions: list[str] = []
    params: list[Any] = []

    for column, value in filters.items():
        if value is not None:
            conditions.append(f"{column} = %s")
            params.append(value)

    if special_conditions:
        conditions.extend(special_conditions)

    if conditions:
        where_clause = sql.SQL(" AND ").join(sql.SQL(c) for c in conditions)  # type: ignore[arg-type]
    else:
        where_clause = sql.SQL("TRUE")

    return where_clause, params


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
    skip_memory_check: bool = False,
) -> dict[str, Any] | None:
    """Create a session diary entry.

    Args:
        skip_memory_check: If True, bypass the memory enabled check.

    Returns:
        The created diary entry, or None if memory is disabled.
    """
    if not skip_memory_check and not is_memory_feature_enabled(project_id, "diary"):
        logger.debug(f"Memory diary disabled for {project_id}, skipping diary entry")
        return None

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
            (
                project_id,
                session_id,
                task_id,
                agent_type,
                duration_seconds,
                tokens_used,
                discovery_tokens,
                outcome,
                observation_type,
                concepts,
                _json_or_default(what_worked),
                _json_or_default(what_failed),
                _json_or_default(user_corrections),
                _json_or_default(patterns_used),
            ),
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
            f"SELECT {DIARY_COLUMNS} FROM session_diary WHERE id = %s",
            (entry_id,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return _diary_row_to_dict(row)


def list_diary_entries(
    project_id: str | None = None,
    outcome: str | None = None,
    unreflected_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List diary entries with optional filters."""
    special = ["reflected_at IS NULL"] if unreflected_only else None
    where_clause, params = _build_where_clause(
        {"project_id": project_id, "outcome": outcome},
        special_conditions=special,
    )
    params.extend([limit, offset])

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL(f"""
            SELECT {DIARY_COLUMNS}
            FROM session_diary
            WHERE {{where_clause}}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """).format(where_clause=where_clause),
            params,
        )
        rows = cur.fetchall()

    return [_diary_row_to_dict(row) for row in rows]


def count_diary_entries(
    project_id: str | None = None,
    outcome: str | None = None,
) -> int:
    """Count diary entries with optional filters.

    Args:
        project_id: Filter by project (None = all projects)
        outcome: Filter by outcome

    Returns:
        Total count of matching diary entries.
    """
    where_clause, params = _build_where_clause(
        {
            "project_id": project_id,
            "outcome": outcome,
        }
    )

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT COUNT(*) FROM session_diary WHERE {where_clause}").format(
                where_clause=where_clause
            ),
            params,
        )
        row = cur.fetchone()
        return row[0] if row else 0


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


def count_diary_entries_since(
    project_id: str,
    hours: int = 24,
) -> int:
    """Count diary entries created in the last N hours.

    Args:
        project_id: Project to count for.
        hours: Time window in hours (default: 24).

    Returns:
        Count of diary entries created within the time window.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM session_diary
            WHERE project_id = %s
              AND created_at >= NOW() - INTERVAL '%s hours'
            """,
            (project_id, hours),
        )
        row = cur.fetchone()
        return row[0] if row else 0


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
            (
                reflection_notes,
                _json_or_default(patterns_generated),
                entry_ids,
            ),
        )
        updated = cur.rowcount
        conn.commit()

    return updated


def get_diary_entry_by_session(project_id: str, session_id: str) -> dict[str, Any] | None:
    """Get diary entry by session ID (for deduplication).

    Returns:
        The diary entry or None if not found.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {DIARY_COLUMNS}
            FROM session_diary
            WHERE project_id = %s AND session_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (project_id, session_id),
        )
        row = cur.fetchone()

    if not row:
        return None
    return _diary_row_to_dict(row)


def _diary_row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert diary row to dict."""
    if row is None:
        raise ValueError("Row cannot be None")
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
