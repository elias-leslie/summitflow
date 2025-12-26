"""Memory storage layer - Observation, Diary, Pattern, and Checkpoint CRUD.

This module provides data access for the Context & Memory Intelligence system.
"""

from __future__ import annotations

import hashlib
import json
import logging
from decimal import Decimal
from typing import Any

from psycopg import sql
from psycopg.rows import TupleRow

from .agent_configs import is_memory_feature_enabled
from .connection import get_connection

# Re-export pattern functions for backward compatibility
from .memory_patterns import (
    count_patterns,
    create_pattern,
    get_pattern,
    get_stale_patterns,
    increment_pattern_usage,
    list_patterns,
    mark_pattern_applied,
    update_pattern_status,
)

# Re-export queue functions for backward compatibility
from .memory_queue import (
    archive_failed_queue_items,
    create_queue_item,
    get_pending_queue_items,
    reset_stuck_queue_items,
    update_queue_item_status,
)

logger = logging.getLogger(__name__)

# Expose queue and pattern functions in __all__ for star imports
__all__ = [
    "archive_failed_queue_items",
    "count_patterns",
    "create_pattern",
    "create_queue_item",
    "get_pattern",
    "get_pending_queue_items",
    "get_stale_patterns",
    "increment_pattern_usage",
    "list_patterns",
    "mark_pattern_applied",
    "reset_stuck_queue_items",
    "update_pattern_status",
    "update_queue_item_status",
]


# Deduplication window in minutes
DEDUP_WINDOW_MINUTES = 60

# Column lists for DRY queries
OBSERVATION_COLUMNS = """
    id, project_id, session_id, agent_type, observation_type,
    concepts, priority, confidence, entities, title, subtitle, narrative, facts, files_read,
    files_modified, tool_name, tool_input, discovery_tokens,
    extracted_by, raw_excerpt, created_at
""".strip()

DIARY_COLUMNS = """
    id, project_id, session_id, task_id, agent_type,
    duration_seconds, tokens_used, discovery_tokens, outcome,
    observation_type, concepts, what_worked, what_failed,
    user_corrections, patterns_used, reflected_at,
    reflection_notes, patterns_generated, created_at
""".strip()


def _json_or_default(obj: Any, default: str | None = None) -> str | None:
    """Serialize object to JSON or return default if falsy.

    Args:
        obj: Object to serialize (list, dict, etc.)
        default: Value to return if obj is falsy (None or "[]")

    Returns:
        JSON string or default value.
    """
    return json.dumps(obj) if obj else default


def _build_where_clause(
    filters: dict[str, Any],
    special_conditions: list[str] | None = None,
) -> tuple[sql.SQL | sql.Composed, list[Any]]:
    """Build a WHERE clause from filters dict.

    Args:
        filters: Dict of {column_name: value} - None values are skipped
        special_conditions: Additional raw SQL conditions (e.g., "reflected_at IS NULL")

    Returns:
        Tuple of (sql.SQL where clause, list of params)
    """
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


def _compute_observation_hash(title: str, observation_type: str, tool_name: str | None) -> str:
    """Compute a short hash for observation deduplication.

    Hash is based on title, type, and tool_name.
    Returns first 16 characters of SHA256 hash.
    """
    content = f"{title}|{observation_type}|{tool_name or ''}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


# =============================================================================
# Observation Queue Storage - see memory_queue.py
# =============================================================================


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
    priority: str = "medium",
    confidence: float = 0.50,
    entities: list[dict[str, str]] | None = None,
    subtitle: str | None = None,
    narrative: str | None = None,
    facts: dict[str, Any] | None = None,
    files_read: list[str] | None = None,
    files_modified: list[str] | None = None,
    tool_name: str | None = None,
    tool_input: dict[str, Any] | None = None,
    discovery_tokens: int = 0,
    extracted_by: str | None = None,
    raw_excerpt: str | None = None,
    skip_memory_check: bool = False,
) -> dict[str, Any] | None:
    """Create an observation from extracted tool execution data.

    Includes deduplication check - if same content_hash exists for this session
    within the deduplication window, returns None to skip duplicate.

    Args:
        skip_memory_check: If True, bypass the memory enabled check.

    Returns:
        The created observation, or None if memory is disabled or duplicate.
    """
    if not skip_memory_check and not is_memory_feature_enabled(project_id, "observations"):
        logger.debug(f"Memory observations disabled for {project_id}, skipping observation")
        return None

    if concepts is None:
        concepts = []
    if files_read is None:
        files_read = []
    if files_modified is None:
        files_modified = []

    # Compute content hash for deduplication
    content_hash = _compute_observation_hash(title, observation_type, tool_name)

    with get_connection() as conn, conn.cursor() as cur:
        # Check for existing duplicate in same session within dedup window
        cur.execute(
            """
            SELECT id FROM observations
            WHERE session_id = %s
              AND content_hash = %s
              AND created_at > NOW() - INTERVAL '%s minutes'
            LIMIT 1
            """,
            (session_id, content_hash, DEDUP_WINDOW_MINUTES),
        )
        existing = cur.fetchone()

        if existing:
            logger.debug(
                f"Duplicate observation skipped: session={session_id[:8]}... "
                f"hash={content_hash} existing_id={existing[0]}"
            )
            return None

        # Insert new observation with content_hash
        cur.execute(
            """
            INSERT INTO observations
                (project_id, session_id, agent_type, observation_type, title,
                 concepts, priority, confidence, entities, subtitle, narrative, facts, files_read, files_modified,
                 tool_name, tool_input, discovery_tokens, extracted_by, raw_excerpt, content_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, project_id, session_id, agent_type, observation_type,
                      concepts, priority, confidence, entities, title, subtitle, narrative, facts, files_read,
                      files_modified, tool_name, tool_input, discovery_tokens,
                      extracted_by, raw_excerpt, created_at
            """,
            (
                project_id,
                session_id,
                agent_type,
                observation_type,
                title,
                concepts,
                priority,
                confidence,
                _json_or_default(entities, "[]"),
                subtitle,
                narrative,
                _json_or_default(facts),
                files_read,
                files_modified,
                tool_name,
                _json_or_default(tool_input),
                discovery_tokens,
                extracted_by,
                raw_excerpt,
                content_hash,
            ),
        )
        row = cur.fetchone()
        conn.commit()

    return _observation_row_to_dict(row)


def get_observation(observation_id: str) -> dict[str, Any] | None:
    """Get an observation by ID."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT {OBSERVATION_COLUMNS} FROM observations WHERE id = %s",
            (observation_id,),
        )
        row = cur.fetchone()

    if not row:
        return None
    return _observation_row_to_dict(row)


def list_observations(
    project_id: str | None = None,
    agent_type: str | None = None,
    observation_type: str | None = None,
    session_id: str | None = None,
    min_confidence: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List observations with optional filters.

    Args:
        project_id: Filter by project (None = all projects)
        agent_type: Filter by agent type
        observation_type: Filter by observation type
        session_id: Filter by session ID
        min_confidence: Filter by minimum confidence score (0.0 - 1.0)
        limit: Maximum results
        offset: Pagination offset

    Returns:
        List of observations sorted by created_at descending.
    """
    # Build special conditions for comparison operators
    special_conditions: list[str] = []
    if min_confidence is not None:
        special_conditions.append("confidence >= %s")

    where_clause, params = _build_where_clause(
        {
            "project_id": project_id,
            "agent_type": agent_type,
            "observation_type": observation_type,
            "session_id": session_id,
        },
        special_conditions=special_conditions,
    )
    # Append special params after the equality params (matching SQL order)
    if min_confidence is not None:
        params.append(min_confidence)
    params.extend([limit, offset])

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL(f"""
            SELECT {OBSERVATION_COLUMNS}
            FROM observations
            WHERE {{where_clause}}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """).format(where_clause=where_clause),
            params,
        )
        rows = cur.fetchall()

    return [_observation_row_to_dict(row) for row in rows]


def count_observations(
    project_id: str | None = None,
    agent_type: str | None = None,
    observation_type: str | None = None,
    session_id: str | None = None,
) -> int:
    """Count observations with optional filters.

    Args:
        project_id: Filter by project (None = all projects)
        agent_type: Filter by agent type
        observation_type: Filter by observation type
        session_id: Filter by session ID

    Returns:
        Total count of matching observations.
    """
    where_clause, params = _build_where_clause(
        {
            "project_id": project_id,
            "agent_type": agent_type,
            "observation_type": observation_type,
            "session_id": session_id,
        }
    )

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT COUNT(*) FROM observations WHERE {where_clause}").format(
                where_clause=where_clause
            ),
            params,
        )
        row = cur.fetchone()
        return row[0] if row else 0


def search_observations_fts(
    project_id: str,
    query: str,
    limit: int = 20,
    use_multi_signal: bool = True,
    query_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Full-text search observations with optional multi-signal ranking.

    Args:
        project_id: Project to search in
        query: Search query string
        limit: Max results
        use_multi_signal: If True, apply multi-signal ranking (recency, confidence, etc.)
        query_types: Optional observation types to boost

    Returns:
        List of observations sorted by relevance.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {OBSERVATION_COLUMNS},
                   ts_rank(search_vector, plainto_tsquery('english', %s)) AS rank
            FROM observations
            WHERE project_id = %s
              AND search_vector @@ plainto_tsquery('english', %s)
            ORDER BY rank DESC
            LIMIT %s
            """,
            (
                query,
                project_id,
                query,
                limit * 2 if use_multi_signal else limit,
            ),  # Fetch more for re-ranking
        )
        rows = cur.fetchall()

    if not use_multi_signal:
        # Original behavior - just FTS ranking
        return [_observation_row_to_dict(row[:21]) for row in rows]

    # Multi-signal ranking
    from app.services.memory.context_builder import ContextBuilder

    results = []
    # Get max rank for normalization
    max_rank = max((row[21] for row in rows), default=1.0) or 1.0

    for row in rows:
        obs = _observation_row_to_dict(row[:21])
        fts_score = row[21] / max_rank  # Normalize FTS score to 0-1
        obs["fts_score"] = round(fts_score, 4)
        obs["combined_score"] = ContextBuilder.rank_observation(
            obs, fts_score=fts_score, query_types=query_types
        )
        results.append(obs)

    # Sort by combined score descending
    results.sort(key=lambda x: x["combined_score"], reverse=True)

    return results[:limit]


def count_observations_since(
    project_id: str,
    hours: int = 2,
) -> int:
    """Count observations created in the last N hours.

    Args:
        project_id: Project to count for.
        hours: Time window in hours (default: 2).

    Returns:
        Count of observations created within the time window.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM observations
            WHERE project_id = %s
              AND created_at >= NOW() - INTERVAL '%s hours'
            """,
            (project_id, hours),
        )
        row = cur.fetchone()
        return row[0] if row else 0


def _observation_row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert observation row to dict.

    Handles row formats with varying columns:
    - 21 cols: with priority, confidence, entities, extracted_by, raw_excerpt (current)
    - 20 cols: with priority, confidence, no entities
    - 19 cols: with priority, raw_excerpt but no confidence
    - 18 cols: with priority and extracted_by, no raw_excerpt
    - 17 cols: with extracted_by, no priority (legacy)
    - 16 cols: no extracted_by, no priority (oldest)
    """
    if row is None:
        raise ValueError("Row cannot be None")

    result = {
        "id": str(row[0]),
        "project_id": row[1],
        "session_id": row[2],
        "agent_type": row[3],
        "observation_type": row[4],
        "concepts": row[5] or [],
    }

    # Current format with entities (21 cols)
    if len(row) >= 21:
        result["priority"] = row[6] or "medium"  # type: ignore[misc]
        confidence = row[7]  # type: ignore[misc]
        result["confidence"] = (
            float(confidence) if isinstance(confidence, Decimal) else (confidence or 0.50)
        )
        result["entities"] = row[8] or []  # type: ignore[misc]
        result["title"] = row[9]  # type: ignore[misc]
        result["subtitle"] = row[10]  # type: ignore[misc]
        result["narrative"] = row[11]  # type: ignore[misc]
        result["facts"] = row[12]  # type: ignore[misc]
        result["files_read"] = row[13] or []  # type: ignore[misc]
        result["files_modified"] = row[14] or []  # type: ignore[misc]
        result["tool_name"] = row[15]  # type: ignore[misc]
        result["tool_input"] = row[16]  # type: ignore[misc]
        result["discovery_tokens"] = row[17]  # type: ignore[misc]
        result["extracted_by"] = row[18]  # type: ignore[misc]
        result["raw_excerpt"] = row[19]  # type: ignore[misc]
        result["created_at"] = row[20].isoformat() if row[20] else None  # type: ignore[misc]
    # Previous format with confidence, no entities (20 cols)
    elif len(row) >= 20:
        result["priority"] = row[6] or "medium"  # type: ignore[misc]
        confidence = row[7]  # type: ignore[misc]
        result["confidence"] = (
            float(confidence) if isinstance(confidence, Decimal) else (confidence or 0.50)
        )
        result["entities"] = []
        result["title"] = row[8]  # type: ignore[misc]
        result["subtitle"] = row[9]  # type: ignore[misc]
        result["narrative"] = row[10]  # type: ignore[misc]
        result["facts"] = row[11]  # type: ignore[misc]
        result["files_read"] = row[12] or []  # type: ignore[misc]
        result["files_modified"] = row[13] or []  # type: ignore[misc]
        result["tool_name"] = row[14]  # type: ignore[misc]
        result["tool_input"] = row[15]  # type: ignore[misc]
        result["discovery_tokens"] = row[16]  # type: ignore[misc]
        result["extracted_by"] = row[17]  # type: ignore[misc]
        result["raw_excerpt"] = row[18]  # type: ignore[misc]
        result["created_at"] = row[19].isoformat() if row[19] else None  # type: ignore[misc]
    # Previous format with raw_excerpt, no confidence (19 cols)
    elif len(row) >= 19:
        result["priority"] = row[6] or "medium"  # type: ignore[misc]
        result["confidence"] = 0.50  # Default for legacy
        result["entities"] = []
        result["title"] = row[7]  # type: ignore[misc]
        result["subtitle"] = row[8]  # type: ignore[misc]
        result["narrative"] = row[9]  # type: ignore[misc]
        result["facts"] = row[10]  # type: ignore[misc]
        result["files_read"] = row[11] or []  # type: ignore[misc]
        result["files_modified"] = row[12] or []  # type: ignore[misc]
        result["tool_name"] = row[13]  # type: ignore[misc]
        result["tool_input"] = row[14]  # type: ignore[misc]
        result["discovery_tokens"] = row[15]  # type: ignore[misc]
        result["extracted_by"] = row[16]  # type: ignore[misc]
        result["raw_excerpt"] = row[17]  # type: ignore[misc]
        result["created_at"] = row[18].isoformat() if row[18] else None  # type: ignore[misc]
    # Previous format with priority, no raw_excerpt (18 cols)
    elif len(row) >= 18:
        result["priority"] = row[6] or "medium"  # type: ignore[misc]
        result["confidence"] = 0.50
        result["entities"] = []
        result["title"] = row[7]  # type: ignore[misc]
        result["subtitle"] = row[8]  # type: ignore[misc]
        result["narrative"] = row[9]  # type: ignore[misc]
        result["facts"] = row[10]  # type: ignore[misc]
        result["files_read"] = row[11] or []  # type: ignore[misc]
        result["files_modified"] = row[12] or []  # type: ignore[misc]
        result["tool_name"] = row[13]  # type: ignore[misc]
        result["tool_input"] = row[14]  # type: ignore[misc]
        result["discovery_tokens"] = row[15]  # type: ignore[misc]
        result["extracted_by"] = row[16]  # type: ignore[misc]
        result["raw_excerpt"] = None
        result["created_at"] = row[17].isoformat() if row[17] else None  # type: ignore[misc]
    # Old format with extracted_by but no priority (17 cols)
    elif len(row) >= 17:
        result["priority"] = "medium"  # Default for legacy data
        result["confidence"] = 0.50
        result["entities"] = []
        result["title"] = row[6]  # type: ignore[misc]
        result["subtitle"] = row[7]  # type: ignore[misc]
        result["narrative"] = row[8]  # type: ignore[misc]
        result["facts"] = row[9]  # type: ignore[misc]
        result["files_read"] = row[10] or []  # type: ignore[misc]
        result["files_modified"] = row[11] or []  # type: ignore[misc]
        result["tool_name"] = row[12]  # type: ignore[misc]
        result["tool_input"] = row[13]  # type: ignore[misc]
        result["discovery_tokens"] = row[14]  # type: ignore[misc]
        result["extracted_by"] = row[15]  # type: ignore[misc]
        result["raw_excerpt"] = None
        result["created_at"] = row[16].isoformat() if row[16] else None  # type: ignore[misc]
    else:
        # Oldest format (16 cols)
        result["priority"] = "medium"
        result["confidence"] = 0.50
        result["entities"] = []
        result["title"] = row[6]  # type: ignore[misc]
        result["subtitle"] = row[7]  # type: ignore[misc]
        result["narrative"] = row[8]  # type: ignore[misc]
        result["facts"] = row[9]  # type: ignore[misc]
        result["files_read"] = row[10] or []  # type: ignore[misc]
        result["files_modified"] = row[11] or []  # type: ignore[misc]
        result["tool_name"] = row[12]  # type: ignore[misc]
        result["tool_input"] = row[13]  # type: ignore[misc]
        result["discovery_tokens"] = row[14]  # type: ignore[misc]
        result["extracted_by"] = None
        result["raw_excerpt"] = None
        result["created_at"] = row[15].isoformat() if row[15] else None  # type: ignore[misc]
    return result


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


def get_observations_by_session(
    project_id: str, session_id: str, limit: int = 100
) -> list[dict[str, Any]]:
    """Get observations for a specific session.

    Returns:
        List of observations for the session.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {OBSERVATION_COLUMNS}
            FROM observations
            WHERE project_id = %s AND session_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (project_id, session_id, limit),
        )
        rows = cur.fetchall()

    return [_observation_row_to_dict(row) for row in rows]


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
    skip_memory_check: bool = False,
) -> dict[str, Any] | None:
    """Create an agent checkpoint.

    Args:
        skip_memory_check: If True, bypass the memory enabled check.

    Returns:
        The created checkpoint, or None if memory is disabled.
    """
    if not skip_memory_check and not is_memory_feature_enabled(project_id, "checkpoints"):
        logger.debug(f"Memory checkpoints disabled for {project_id}, skipping checkpoint")
        return None

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
            (
                project_id,
                session_id,
                agent_type,
                current_action,
                question,
                _json_or_default(options),
                recommendation,
                _json_or_default(completed_steps),
                _json_or_default(remaining_steps),
                _json_or_default(files_modified),
                _json_or_default(decisions_made),
                conversation_summary,
                _json_or_default(context_snapshot),
                tokens_used,
            ),
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


def _checkpoint_row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert checkpoint row to dict."""
    if row is None:
        raise ValueError("Row cannot be None")
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


# =============================================================================
# Lifecycle Stats
# =============================================================================


def get_lifecycle_stats(project_id: str | None = None) -> dict[str, Any]:
    """Get lifecycle health statistics for the memory system.

    Args:
        project_id: Optional project filter. If None, returns global stats.

    Returns:
        Dict with lifecycle metrics:
        - failed_queue_count: Queue items in failed status
        - stuck_queue_count: Queue items stuck in processing > 1 hour
        - oldest_pending_age_minutes: Age of oldest pending queue item
        - unreflected_diary_count: Diary entries never reflected
        - stale_patterns_count: Applied patterns unused for 30+ days
        - pattern_status_breakdown: Count by status
    """
    project_filter = "AND project_id = %s" if project_id else ""
    params: list[Any] = [project_id] if project_id else []

    with get_connection() as conn, conn.cursor() as cur:
        # Failed queue count
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM observation_queue
            WHERE status = 'failed'
            {project_filter}
            """,
            params,
        )
        row = cur.fetchone()
        failed_queue_count = row[0] if row else 0

        # Stuck queue count (processing for > 1 hour)
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM observation_queue
            WHERE status = 'processing'
              AND created_at < NOW() - INTERVAL '1 hour'
            {project_filter}
            """,
            params,
        )
        row = cur.fetchone()
        stuck_queue_count = row[0] if row else 0

        # Oldest pending age in minutes
        cur.execute(
            f"""
            SELECT EXTRACT(EPOCH FROM (NOW() - MIN(created_at))) / 60
            FROM observation_queue
            WHERE status = 'pending'
            {project_filter}
            """,
            params,
        )
        row = cur.fetchone()
        result = row[0] if row else None
        oldest_pending_age_minutes = int(result) if result else None

        # Unreflected diary count
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM session_diary
            WHERE reflected_at IS NULL
            {project_filter}
            """,
            params,
        )
        row = cur.fetchone()
        unreflected_diary_count = row[0] if row else 0

        # Stale patterns count (applied but unused for 30+ days)
        cur.execute(
            f"""
            SELECT COUNT(*)
            FROM learned_patterns
            WHERE status = 'applied'
              AND (last_used_at IS NULL OR last_used_at < NOW() - INTERVAL '30 days')
            {project_filter}
            """,
            params,
        )
        row = cur.fetchone()
        stale_patterns_count = row[0] if row else 0

        # Pattern status breakdown
        cur.execute(
            f"""
            SELECT status, COUNT(*)
            FROM learned_patterns
            WHERE 1=1
            {project_filter}
            GROUP BY status
            """,
            params,
        )
        pattern_status_breakdown = {row[0]: row[1] for row in cur.fetchall()}

    return {
        "failed_queue_count": failed_queue_count,
        "stuck_queue_count": stuck_queue_count,
        "oldest_pending_age_minutes": oldest_pending_age_minutes,
        "unreflected_diary_count": unreflected_diary_count,
        "stale_patterns_count": stale_patterns_count,
        "pattern_status_breakdown": pattern_status_breakdown,
    }


# =============================================================================
# Lifecycle Cleanup Functions
# =============================================================================


def cleanup_old_checkpoints(max_age_days: int = 30) -> int:
    """Delete old checkpoints beyond the retention period.

    Args:
        max_age_days: Delete checkpoints older than this many days.

    Returns:
        Number of checkpoints deleted.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM agent_checkpoints
            WHERE created_at < NOW() - INTERVAL '%s days'
            """,
            (max_age_days,),
        )
        deleted = cur.rowcount
        conn.commit()

    logger.info(
        f"cleanup_old_checkpoints: deleted {deleted} checkpoints older than {max_age_days} days"
    )
    return deleted
