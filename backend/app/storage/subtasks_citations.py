"""Subtask citation handling - memory usage tracking and rating.

This module handles memory citation parsing, logging, and acknowledgment
for subtasks, supporting Agent Hub ACE-aligned tier optimization.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from .connection import get_connection

logger = logging.getLogger(__name__)


def parse_citation(citation: str) -> tuple[str, str]:
    """Parse a citation in suffix notation to (episode_uuid_prefix, rating).

    Args:
        citation: Citation string like "M:abc12345+" or "G:def67890-" or "M:xyz99999"
                  Also handles bracket format: "[M:abc12345]"

    Returns:
        Tuple of (uuid_prefix, rating) where rating is 'helpful', 'harmful', or 'used'
    """
    clean = citation.strip("[]")
    prefix = clean[2:10]
    suffix = clean[10:] if len(clean) > 10 else ""
    if suffix == "+":
        rating = "helpful"
    elif suffix == "-":
        rating = "harmful"
    else:
        rating = "used"
    return prefix, rating


def _build_parsed_citations(citations: list[str]) -> list[tuple[str, str]]:
    """Convert raw citation strings to (uuid_prefix, rating) pairs.

    Supports suffix notation (M:abc12345+) and plain UUID strings.
    """
    parsed: list[tuple[str, str]] = []
    for c in citations:
        if ":" in c:
            parsed.append(parse_citation(c))
        else:
            parsed.append((c, "used"))
    return parsed


def _persist_citations(
    subtask_table_id: str,
    parsed: list[tuple[str, str]],
    now: datetime,
) -> None:
    """Insert citation rows and stamp citations_acknowledged_at in one transaction."""
    with get_connection() as conn, conn.cursor() as cur:
        for uuid_prefix, rating in parsed:
            cur.execute(
                """
                INSERT INTO subtask_citations (subtask_id, episode_uuid, rating)
                VALUES (%s, %s, %s)
                """,
                (subtask_table_id, uuid_prefix, rating),
            )
        cur.execute(
            """
            UPDATE task_subtasks SET citations_acknowledged_at = %s WHERE id = %s
            """,
            (now, subtask_table_id),
        )
        conn.commit()


def _send_ratings_to_hub(
    client: Any,
    parsed: list[tuple[str, str]],
) -> None:
    """Send episode ratings to Agent Hub for ACE-aligned tier optimization."""
    for uuid_prefix, rating in parsed:
        try:
            client.rate_episode(uuid_prefix, rating)
        except Exception as e:
            logger.warning("Failed to send rating to Agent Hub: %s", e)


def log_citations(
    subtask_table_id: str,
    citations: list[str],
    client: Any | None = None,
) -> int:
    """Log episode citations for a subtask with ratings.

    Parses suffix notation and stores in subtask_citations table.
    Also sends ratings to Agent Hub for ACE-aligned tier optimization.
    Sets citations_acknowledged_at to mark that agent reflected on memory usage.

    Args:
        subtask_table_id: Full subtask table ID (e.g., "task-abc123-1.1")
        citations: List of citations in suffix notation or plain UUIDs
        client: Optional Agent Hub client for sending ratings

    Returns:
        Number of citations logged
    """
    if not citations:
        return 0

    parsed = _build_parsed_citations(citations)
    _persist_citations(subtask_table_id, parsed, datetime.now(UTC))

    if client is not None:
        _send_ratings_to_hub(client, parsed)

    logger.info("Logged %d citations for subtask %s", len(parsed), subtask_table_id)
    return len(parsed)


def acknowledge_no_citations(subtask_table_id: str) -> bool:
    """Acknowledge that no memories were needed for this subtask.

    Called when agent confirms they didn't use any provided memories.
    Sets citations_acknowledged_at without creating citation records.

    Args:
        subtask_table_id: Full subtask table ID (e.g., "task-abc123-1.1")

    Returns:
        True if acknowledged successfully
    """
    now = datetime.now(UTC)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE task_subtasks SET citations_acknowledged_at = %s
            WHERE id = %s
            RETURNING id
            """,
            (now, subtask_table_id),
        )
        row = cur.fetchone()
        conn.commit()

    if row:
        logger.info("Acknowledged no citations for subtask %s", subtask_table_id)
        return True
    return False
