"""Memory observations storage - Observation CRUD operations.

This module handles the observations table operations.
"""

from __future__ import annotations

import hashlib
import logging
from decimal import Decimal
from typing import Any, TypedDict

from psycopg import sql
from psycopg.rows import TupleRow

from .agent_configs import is_memory_feature_enabled
from .connection import get_connection
from .memory_utils import (
    build_where_clause,
    json_or_default,
    normalize_timestamp,
)

logger = logging.getLogger(__name__)

# Deduplication window in minutes
DEDUP_WINDOW_MINUTES = 60

# Column list for DRY queries
OBSERVATION_COLUMNS = """
    id, project_id, session_id, agent_type, observation_type,
    concepts, priority, confidence, entities, title, subtitle, narrative, facts, files_read,
    files_modified, tool_name, tool_input, discovery_tokens,
    extracted_by, raw_excerpt, created_at
""".strip()


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
    fts_score: float
    combined_score: float
    similarity_score: float


def _normalize_confidence(value: Decimal | float | None, default: float = 0.50) -> float:
    """Convert Decimal confidence to float, or return default if None."""
    if isinstance(value, Decimal):
        return float(value)
    return value if value is not None else default


def _compute_observation_hash(title: str, observation_type: str, tool_name: str | None) -> str:
    """Compute a short hash for observation deduplication.

    Hash is based on title, type, and tool_name.
    Returns first 16 characters of SHA256 hash.
    """
    content = f"{title}|{observation_type}|{tool_name or ''}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


# Column mappings by row length (version-based parser selection)
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
        for known_len in sorted(_OBSERVATION_ROW_FORMATS.keys(), reverse=True):
            if row_len >= known_len:
                format_info = _OBSERVATION_ROW_FORMATS[known_len]
                break
        else:
            format_info = (0, False, False, False)

    _, has_priority, has_confidence, has_entities = format_info

    result: dict[str, Any] = {
        "id": str(row[0]),
        "project_id": row[1],
        "session_id": row[2],
        "agent_type": row[3],
        "observation_type": row[4],
        "concepts": row[5] or [],
    }

    idx = 6
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

    result["title"] = row[idx]
    result["subtitle"] = row[idx + 1]
    result["narrative"] = row[idx + 2]
    result["facts"] = row[idx + 3]
    result["files_read"] = row[idx + 4] or []
    result["files_modified"] = row[idx + 5] or []
    result["tool_name"] = row[idx + 6]
    result["tool_input"] = row[idx + 7]
    result["discovery_tokens"] = row[idx + 8]

    remaining = row_len - (idx + 9)
    if remaining >= 3:
        result["extracted_by"] = row[idx + 9]
        result["raw_excerpt"] = row[idx + 10]
        result["created_at"] = normalize_timestamp(row[idx + 11])
    elif remaining >= 2:
        result["extracted_by"] = row[idx + 9]
        result["raw_excerpt"] = None
        result["created_at"] = normalize_timestamp(row[idx + 10])
    else:
        result["extracted_by"] = None
        result["raw_excerpt"] = None
        result["created_at"] = normalize_timestamp(row[idx + 9])

    return result


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

    content_hash = _compute_observation_hash(title, observation_type, tool_name)

    with get_connection() as conn, conn.cursor() as cur:
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
                json_or_default(entities, "[]"),
                subtitle,
                narrative,
                json_or_default(facts),
                files_read,
                files_modified,
                tool_name,
                json_or_default(tool_input),
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
    special_conditions: list[str] = []
    if min_confidence is not None:
        special_conditions.append("confidence >= %s")

    where_clause, params = build_where_clause(
        {
            "project_id": project_id,
            "agent_type": agent_type,
            "observation_type": observation_type,
            "session_id": session_id,
        },
        special_conditions=special_conditions,
    )
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


def query_observations(
    project_id: str,
    observation_type: str,
    min_confidence: float = 0.0,
    days: int = 7,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Query observations by type with confidence and time filters.

    Optimized for autonomous task generation from error observations.

    Args:
        project_id: Project to query.
        observation_type: Filter by observation type (e.g., 'error', 'decision').
        min_confidence: Minimum confidence score (0.0 - 1.0).
        days: Only include observations from the last N days.
        limit: Maximum results to return.

    Returns:
        List of observations with id, title, narrative, files, confidence, created_at.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, title, narrative, files_modified, confidence, created_at
            FROM observations
            WHERE project_id = %s
              AND observation_type = %s
              AND confidence >= %s
              AND created_at >= NOW() - INTERVAL '%s days'
            ORDER BY confidence DESC, created_at DESC
            LIMIT %s
            """,
            (project_id, observation_type, min_confidence, days, limit),
        )
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "title": row[1],
            "narrative": row[2],
            "files": row[3] or [],
            "confidence": float(row[4]) if row[4] else 0.0,
            "created_at": row[5].isoformat() if row[5] else None,
        }
        for row in rows
    ]


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
    where_clause, params = build_where_clause(
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
            ),
        )
        rows = cur.fetchall()

    if not use_multi_signal:
        return [_observation_row_to_dict(row[:21]) for row in rows]

    from .memory_utils import rank_observation

    results = []
    max_rank = max((row[21] for row in rows), default=1.0) or 1.0

    for row in rows:
        obs = _observation_row_to_dict(row[:21])
        fts_score = row[21] / max_rank
        obs["fts_score"] = round(fts_score, 4)
        obs["combined_score"] = rank_observation(obs, fts_score=fts_score, query_types=query_types)
        results.append(obs)

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
