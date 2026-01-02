"""Memory embedding storage functions for semantic search.

Functions for managing observation embeddings and semantic similarity search
using pgvector.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from psycopg import sql

from .connection import get_connection
from .memory_utils import calculate_recency_score, normalize_timestamp

logger = logging.getLogger(__name__)

# Column list for observation queries
OBSERVATION_COLUMNS = """
    id, project_id, session_id, agent_type, observation_type,
    concepts, title, subtitle, narrative, facts,
    files_read, files_modified, tool_name, tool_input,
    discovery_tokens, created_at, patterns_derived,
    embedding_narrative, embedding_title, confidence, usage_count
"""


def _observation_row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert observation row tuple to dict."""
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
        "facts": row[9] or [],
        "files_read": row[10] or [],
        "files_modified": row[11] or [],
        "tool_name": row[12],
        "tool_input": row[13],
        "discovery_tokens": row[14],
        "created_at": normalize_timestamp(row[15]),
        "patterns_derived": row[16] or [],
        "embedding_narrative": row[17] is not None,
        "embedding_title": row[18] is not None,
        "confidence": float(row[19]) if row[19] else 0.5,
        "usage_count": row[20] or 0,
    }


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
        return [_observation_row_to_dict_short(row) for row in cur.fetchall()]


def _observation_row_to_dict_short(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert short observation row (16 columns) to dict."""
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
        "facts": row[9] or [],
        "files_read": row[10] or [],
        "files_modified": row[11] or [],
        "tool_name": row[12],
        "tool_input": row[13],
        "discovery_tokens": row[14],
        "created_at": normalize_timestamp(row[15]),
    }


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
        updated: int = cur.rowcount
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

    results = []

    for row in rows:
        obs = _observation_row_to_dict(row[:21])
        similarity = float(row[21])
        recency_score = calculate_recency_score(obs.get("created_at"))

        confidence = obs.get("confidence", 0.5)
        confidence_score = min(1.0, max(0.0, float(confidence)))

        usage = obs.get("usage_count", 0)
        usage_score = min(1.0, usage / 10.0) if usage else 0.0

        combined = (
            0.50 * similarity + 0.30 * recency_score + 0.15 * confidence_score + 0.05 * usage_score
        )

        obs["similarity_score"] = round(similarity, 4)
        obs["combined_score"] = round(combined, 4)
        results.append(obs)

    results.sort(key=lambda x: x["combined_score"], reverse=True)
    return results


def find_similar_patterns(
    pattern_id: str,
    project_id: str | None = None,
    min_similarity: float = 0.85,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Find patterns similar to a given pattern using vector similarity.

    Uses pgvector's cosine distance for pattern deduplication.
    Only searches patterns that have embeddings.

    Args:
        pattern_id: Pattern ID to find similar patterns for
        project_id: Optional project filter (None = search all projects)
        min_similarity: Minimum cosine similarity threshold (default 0.85)
        limit: Maximum number of similar patterns to return

    Returns:
        List of {pattern_id, similarity_score} dicts, excluding the source pattern.
        Empty list if source pattern has no embedding.
    """
    with get_connection() as conn, conn.cursor() as cur:
        # First, get the embedding for the source pattern
        cur.execute(
            "SELECT embedding FROM learned_patterns WHERE id = %s",
            (pattern_id,),
        )
        row = cur.fetchone()

        if not row or row[0] is None:
            logger.debug(f"Pattern {pattern_id} has no embedding, cannot find similar")
            return []

        source_embedding = row[0]

        # Find similar patterns
        if project_id:
            cur.execute(
                """
                SELECT id, 1 - (embedding <=> %s::vector) AS similarity
                FROM learned_patterns
                WHERE id != %s
                  AND embedding IS NOT NULL
                  AND project_id = %s
                  AND 1 - (embedding <=> %s::vector) >= %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (
                    source_embedding,
                    pattern_id,
                    project_id,
                    source_embedding,
                    min_similarity,
                    source_embedding,
                    limit,
                ),
            )
        else:
            cur.execute(
                """
                SELECT id, 1 - (embedding <=> %s::vector) AS similarity
                FROM learned_patterns
                WHERE id != %s
                  AND embedding IS NOT NULL
                  AND 1 - (embedding <=> %s::vector) >= %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (
                    source_embedding,
                    pattern_id,
                    source_embedding,
                    min_similarity,
                    source_embedding,
                    limit,
                ),
            )

        rows = cur.fetchall()

    return [
        {"pattern_id": str(row[0]), "similarity_score": round(float(row[1]), 4)} for row in rows
    ]


def get_patterns_without_embeddings(
    project_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Get patterns that don't have embeddings yet.

    Args:
        project_id: Optional project ID to filter by
        limit: Maximum number of results

    Returns:
        List of patterns needing embeddings (id, title, content)
    """
    with get_connection() as conn, conn.cursor() as cur:
        if project_id:
            cur.execute(
                """
                SELECT id, project_id, title, content
                FROM learned_patterns
                WHERE embedding IS NULL
                  AND project_id = %s
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (project_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT id, project_id, title, content
                FROM learned_patterns
                WHERE embedding IS NULL
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
                "content": row[3],
            }
            for row in cur.fetchall()
        ]


def update_pattern_embedding(pattern_id: str, embedding: list[float]) -> bool:
    """Update the embedding for a pattern.

    Args:
        pattern_id: Pattern ID to update
        embedding: 768-dimensional embedding vector

    Returns:
        True if updated, False if pattern not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE learned_patterns SET embedding = %s WHERE id = %s",
            (embedding, pattern_id),
        )
        updated: bool = cur.rowcount > 0
        conn.commit()
        if updated:
            logger.debug(f"Updated embedding for pattern {pattern_id}")
        return updated
