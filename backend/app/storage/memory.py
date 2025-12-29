"""Memory storage layer - Observation, Diary, Pattern, and Checkpoint CRUD.

This module provides data access for the Context & Memory Intelligence system.
"""

from __future__ import annotations

import hashlib
import logging
import math
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, TypedDict

from psycopg import sql
from psycopg.rows import TupleRow

from .agent_configs import is_memory_feature_enabled
from .connection import get_connection

# Re-export diary functions for backward compatibility
from .memory_diary import (
    count_diary_entries,
    count_diary_entries_since,
    create_diary_entry,
    get_diary_entry,
    get_diary_entry_by_session,
    get_projects_needing_reflection,
    get_unreflected_diary_count,
    list_diary_entries,
    mark_diary_entries_reflected,
)

# Re-export pattern functions for backward compatibility
from .memory_patterns import (
    count_patterns,
    create_pattern,
    get_pattern,
    get_stale_patterns,
    increment_pattern_usage,
    list_patterns,
    mark_pattern_applied,
    update_pattern_feedback,
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
from .memory_utils import build_where_clause, json_or_default

# =============================================================================
# TypedDicts for documentation/IDE support
# =============================================================================


class ObservationDict(TypedDict, total=False):
    """Type definition for observation data."""

    id: str
    project_id: str
    session_id: str
    agent_type: str
    observation_type: str
    concepts: list[str]
    priority: str
    confidence: float
    entities: list[str]
    title: str | None
    subtitle: str | None
    narrative: str | None
    facts: list[str] | None
    files_read: list[str]
    files_modified: list[str]
    tool_name: str | None
    tool_input: str | None
    discovery_tokens: int | None
    extracted_by: str | None
    raw_excerpt: str | None
    created_at: str | None
    # Optional fields added by search functions
    fts_score: float
    combined_score: float
    similarity_score: float


class CheckpointDict(TypedDict, total=False):
    """Type definition for checkpoint data."""

    id: str
    project_id: str
    session_id: str
    agent_type: str
    current_action: str | None
    question: str | None
    options: list[str] | None
    recommendation: str | None
    completed_steps: list[str] | None
    remaining_steps: list[str] | None
    files_modified: list[str] | None
    decisions_made: list[str] | None
    conversation_summary: str | None
    context_snapshot: dict[str, Any] | None
    tokens_used: int | None
    created_at: str | None


logger = logging.getLogger(__name__)

# Alias for internal use (maintains underscore convention)
_json_or_default = json_or_default
_build_where_clause = build_where_clause

# Expose queue, diary, and pattern functions in __all__ for star imports
__all__ = [
    "archive_failed_queue_items",
    "count_diary_entries",
    "count_diary_entries_since",
    "count_patterns",
    "create_diary_entry",
    "create_pattern",
    "create_queue_item",
    "get_diary_entry",
    "get_diary_entry_by_session",
    "get_pattern",
    "get_pending_queue_items",
    "get_projects_needing_reflection",
    "get_stale_patterns",
    "get_unreflected_diary_count",
    "increment_pattern_usage",
    "list_diary_entries",
    "list_patterns",
    "mark_diary_entries_reflected",
    "mark_pattern_applied",
    "reset_stuck_queue_items",
    "update_pattern_feedback",
    "update_pattern_status",
    "update_queue_item_status",
]


# Deduplication window in minutes
DEDUP_WINDOW_MINUTES = 60

# Time interval constants
STUCK_QUEUE_THRESHOLD = "1 hour"


def _normalize_confidence(value: Decimal | float | None, default: float = 0.50) -> float:
    """Convert Decimal confidence to float, or return default if None."""
    if isinstance(value, Decimal):
        return float(value)
    return value if value is not None else default


STALE_PATTERN_THRESHOLD = "30 days"
DEFAULT_CHECKPOINT_RETENTION_DAYS = 30

# Column lists for DRY queries
OBSERVATION_COLUMNS = """
    id, project_id, session_id, agent_type, observation_type,
    concepts, priority, confidence, entities, title, subtitle, narrative, facts, files_read,
    files_modified, tool_name, tool_input, discovery_tokens,
    extracted_by, raw_excerpt, created_at
""".strip()

CHECKPOINT_COLUMNS = """
    id, project_id, session_id, agent_type, current_action,
    question, options, recommendation, completed_steps,
    remaining_steps, files_modified, decisions_made,
    conversation_summary, context_snapshot, tokens_used, created_at
""".strip()


def _fetch_count(cur: Any, sql: str, params: list[Any]) -> int:
    """Execute SQL and return count from first row, or 0 if no result."""
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else 0


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


# Column mappings by row length (version-based parser selection)
# Format: (offset_from_concepts, has_priority, has_confidence, has_entities)
_OBSERVATION_ROW_FORMATS: dict[int, tuple[int, bool, bool, bool]] = {
    21: (1, True, True, True),  # current: priority, confidence, entities
    20: (1, True, True, False),  # priority, confidence, no entities
    19: (1, True, False, False),  # priority, raw_excerpt, no confidence
    18: (1, True, False, False),  # priority, extracted_by, no raw_excerpt
    17: (0, False, False, False),  # extracted_by, no priority
    16: (0, False, False, False),  # oldest: no extracted_by, no priority
}


def _observation_row_to_dict(row: TupleRow | tuple[Any, ...] | None) -> dict[str, Any]:
    """Convert observation row to dict.

    Handles legacy row formats using version-based parser selection.
    """
    if row is None:
        raise ValueError("Row cannot be None")

    row_len = len(row)
    format_info = _OBSERVATION_ROW_FORMATS.get(row_len)
    if format_info is None:
        # Find closest known format
        for known_len in sorted(_OBSERVATION_ROW_FORMATS.keys(), reverse=True):
            if row_len >= known_len:
                format_info = _OBSERVATION_ROW_FORMATS[known_len]
                break
        else:
            format_info = (0, False, False, False)  # Fallback to oldest

    _, has_priority, has_confidence, has_entities = format_info

    # Base fields (always present)
    result: dict[str, Any] = {
        "id": str(row[0]),
        "project_id": row[1],
        "session_id": row[2],
        "agent_type": row[3],
        "observation_type": row[4],
        "concepts": row[5] or [],
    }

    # Parse based on format version
    idx = 6  # Start after concepts
    if has_priority:
        result["priority"] = row[idx] or "medium"
        idx += 1
    else:
        result["priority"] = "medium"

    if has_confidence:
        result["confidence"] = _normalize_confidence(row[idx])
        idx += 1
    else:
        result["confidence"] = 0.50

    if has_entities:
        result["entities"] = row[idx] or []
        idx += 1
    else:
        result["entities"] = []

    # Remaining fields follow sequentially
    result["title"] = row[idx]
    result["subtitle"] = row[idx + 1]
    result["narrative"] = row[idx + 2]
    result["facts"] = row[idx + 3]
    result["files_read"] = row[idx + 4] or []
    result["files_modified"] = row[idx + 5] or []
    result["tool_name"] = row[idx + 6]
    result["tool_input"] = row[idx + 7]
    result["discovery_tokens"] = row[idx + 8]

    # extracted_by and raw_excerpt depend on row length
    remaining = row_len - (idx + 9)
    if remaining >= 3:  # extracted_by, raw_excerpt, created_at
        result["extracted_by"] = row[idx + 9]
        result["raw_excerpt"] = row[idx + 10]
        result["created_at"] = row[idx + 11].isoformat() if row[idx + 11] else None
    elif remaining >= 2:  # extracted_by, created_at (no raw_excerpt)
        result["extracted_by"] = row[idx + 9]
        result["raw_excerpt"] = None
        result["created_at"] = row[idx + 10].isoformat() if row[idx + 10] else None
    else:  # Only created_at
        result["extracted_by"] = None
        result["raw_excerpt"] = None
        result["created_at"] = row[idx + 9].isoformat() if row[idx + 9] else None

    return result


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
            f"""
            SELECT {CHECKPOINT_COLUMNS}
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
            f"""
            SELECT {CHECKPOINT_COLUMNS}
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
        failed_queue_count = _fetch_count(
            cur,
            f"""
            SELECT COUNT(*)
            FROM observation_queue
            WHERE status = 'failed'
            {project_filter}
            """,
            params,
        )

        # Stuck queue count (processing for > 1 hour)
        stuck_queue_count = _fetch_count(
            cur,
            f"""
            SELECT COUNT(*)
            FROM observation_queue
            WHERE status = 'processing'
              AND created_at < NOW() - INTERVAL '{STUCK_QUEUE_THRESHOLD}'
            {project_filter}
            """,
            params,
        )

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
        unreflected_diary_count = _fetch_count(
            cur,
            f"""
            SELECT COUNT(*)
            FROM session_diary
            WHERE reflected_at IS NULL
            {project_filter}
            """,
            params,
        )

        # Stale patterns count (applied but unused for 30+ days)
        stale_patterns_count = _fetch_count(
            cur,
            f"""
            SELECT COUNT(*)
            FROM learned_patterns
            WHERE status = 'applied'
              AND (last_used_at IS NULL OR last_used_at < NOW() - INTERVAL '{STALE_PATTERN_THRESHOLD}')
            {project_filter}
            """,
            params,
        )

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


def cleanup_old_checkpoints(max_age_days: int = DEFAULT_CHECKPOINT_RETENTION_DAYS) -> int:
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


# =============================================================================
# Embedding Functions for Semantic Search
# =============================================================================


def get_observations_without_embeddings(
    project_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Get observations that don't have embeddings yet.

    Args:
        project_id: Optional project ID to filter by
        limit: Maximum number of results

    Returns:
        List of observations needing embeddings (id, title, narrative)
    """
    with get_connection() as conn, conn.cursor() as cur:
        if project_id:
            cur.execute(
                """
                SELECT id, project_id, title, narrative
                FROM observations
                WHERE embedding_narrative IS NULL
                  AND narrative IS NOT NULL
                  AND project_id = %s
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (project_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT id, project_id, title, narrative
                FROM observations
                WHERE embedding_narrative IS NULL
                  AND narrative IS NOT NULL
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (limit,),
            )
        return [
            {
                "id": str(row[0]),
                "project_id": row[1],
                "title": row[2],
                "narrative": row[3],
            }
            for row in cur.fetchall()
        ]


def _get_observations_by_time(
    project_id: str,
    reference_time: str,
    direction: Literal["before", "after"],
    exclude_id: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Get observations before or after a specific time.

    Args:
        project_id: The project ID
        reference_time: ISO timestamp to query around
        direction: 'before' or 'after' the reference time
        exclude_id: Optional observation ID to exclude
        limit: Maximum number of results

    Returns:
        List of observations (DESC for before, ASC for after)
    """
    comparison = "<" if direction == "before" else ">"
    sort_order = "DESC" if direction == "before" else "ASC"

    query = sql.SQL("""
        SELECT id, project_id, session_id, agent_type,
               observation_type, concepts, title, subtitle,
               narrative, facts, files_read, files_modified,
               tool_name, tool_input, discovery_tokens, created_at
        FROM observations
        WHERE project_id = %s
          AND created_at {comparison} %s
          {exclude_clause}
        ORDER BY created_at {sort_order}
        LIMIT %s
    """).format(
        comparison=sql.SQL(comparison),
        exclude_clause=sql.SQL("AND id != %s") if exclude_id else sql.SQL(""),
        sort_order=sql.SQL(sort_order),
    )

    params: list[Any] = [project_id, reference_time]
    if exclude_id:
        params.append(exclude_id)
    params.append(limit)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(query, tuple(params))
        return [_observation_row_to_dict(row) for row in cur.fetchall()]


def get_observations_before_time(
    project_id: str,
    before_time: str,
    exclude_id: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Get observations before a specific time."""
    return _get_observations_by_time(
        project_id=project_id,
        reference_time=before_time,
        direction="before",
        exclude_id=exclude_id,
        limit=limit,
    )


def get_observations_after_time(
    project_id: str,
    after_time: str,
    exclude_id: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Get observations after a specific time."""
    return _get_observations_by_time(
        project_id=project_id,
        reference_time=after_time,
        direction="after",
        exclude_id=exclude_id,
        limit=limit,
    )


def bulk_update_observation_embeddings(
    updates: list[tuple[str, list[float], list[float]]],
) -> int:
    """Bulk update embeddings for multiple observations.

    Args:
        updates: List of (observation_id, embedding_narrative, embedding_title) tuples

    Returns:
        Number of observations updated
    """
    if not updates:
        return 0

    with get_connection() as conn, conn.cursor() as cur:
        # Use executemany for batch update
        cur.executemany(
            """
            UPDATE observations
            SET embedding_narrative = %s,
                embedding_title = %s
            WHERE id = %s
            """,
            [(emb_narrative, emb_title, obs_id) for obs_id, emb_narrative, emb_title in updates],
        )
        conn.commit()
        updated = cur.rowcount
        logger.info(f"Bulk updated {updated} observation embeddings")
        return updated


def has_embeddings(project_id: str | None = None) -> bool:
    """Check if any observations have embeddings.

    Args:
        project_id: Optional project ID to check

    Returns:
        True if at least one observation has embedding_narrative
    """
    with get_connection() as conn, conn.cursor() as cur:
        if project_id:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM observations
                    WHERE embedding_narrative IS NOT NULL
                      AND project_id = %s
                    LIMIT 1
                )
                """,
                (project_id,),
            )
        else:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM observations
                    WHERE embedding_narrative IS NOT NULL
                    LIMIT 1
                )
                """
            )
        result = cur.fetchone()
        return bool(result and result[0])


def search_observations_semantic(
    project_id: str,
    query_embedding: list[float],
    limit: int = 20,
    min_similarity: float = 0.5,
) -> list[dict[str, Any]]:
    """Semantic search observations using vector similarity.

    Uses pgvector's cosine distance operator (<=>) for similarity search.
    Combines similarity score with recency and confidence for final ranking.

    Args:
        project_id: Project to search in
        query_embedding: 768-dimensional embedding vector for the query
        limit: Max results
        min_similarity: Minimum similarity threshold (0-1)

    Returns:
        List of observations with similarity_score and combined_score
    """
    with get_connection() as conn, conn.cursor() as cur:
        # Cosine distance to similarity: 1 - distance
        # Filter by minimum similarity threshold
        cur.execute(
            f"""
            SELECT {OBSERVATION_COLUMNS},
                   1 - (embedding_narrative <=> %s::vector) AS similarity
            FROM observations
            WHERE project_id = %s
              AND embedding_narrative IS NOT NULL
              AND 1 - (embedding_narrative <=> %s::vector) >= %s
            ORDER BY embedding_narrative <=> %s::vector
            LIMIT %s
            """,
            (
                query_embedding,
                project_id,
                query_embedding,
                min_similarity,
                query_embedding,
                limit,
            ),
        )
        rows = cur.fetchall()

    if not rows:
        return []

    # Apply recency-weighted ranking
    # Weights: similarity=0.50, recency=0.30, confidence=0.15, usage=0.05
    results = []
    now = datetime.now(UTC)

    for row in rows:
        obs = _observation_row_to_dict(row[:21])
        similarity = float(row[21])

        # Recency score: exp(-age_days / 30)
        recency_score = 0.5
        try:
            created_at = obs.get("created_at")
            if created_at:
                if isinstance(created_at, str):
                    created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                else:
                    created_dt = created_at
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=UTC)
                age_days = (now - created_dt).total_seconds() / 86400
                recency_score = math.exp(-age_days / 30)
        except (ValueError, TypeError):
            pass

        # Confidence score
        confidence = obs.get("confidence", 0.5)
        confidence_score = min(1.0, max(0.0, float(confidence)))

        # Usage score (capped at 10)
        usage = obs.get("usage_count", 0)
        usage_score = min(1.0, usage / 10.0) if usage else 0.0

        # Combined score with semantic similarity as primary signal
        combined = (
            0.50 * similarity + 0.30 * recency_score + 0.15 * confidence_score + 0.05 * usage_score
        )

        obs["similarity_score"] = round(similarity, 4)
        obs["combined_score"] = round(combined, 4)
        results.append(obs)

    # Sort by combined score descending
    results.sort(key=lambda x: x["combined_score"], reverse=True)
    return results
