"""Memory prompts storage - User prompt capture for semantic search.

This module handles the user_prompts table operations.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from .agent_configs import is_memory_feature_enabled
from .connection import get_connection

logger = logging.getLogger(__name__)

# Column list for DRY queries
PROMPT_COLUMNS = """
    id, project_id, session_id, prompt_number, prompt_text, embedding, created_at
""".strip()


def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert a row tuple to a dictionary."""
    return {
        "id": str(row[0]),
        "project_id": row[1],
        "session_id": row[2],
        "prompt_number": row[3],
        "prompt_text": row[4],
        "embedding": list(row[5]) if row[5] else None,
        "created_at": row[6].isoformat() if row[6] else None,
    }


def create_user_prompt(
    project_id: str,
    session_id: str,
    prompt_number: int,
    prompt_text: str,
    embedding: list[float] | None = None,
    skip_memory_check: bool = False,
) -> dict[str, Any] | None:
    """Create a user prompt entry.

    Args:
        project_id: The project ID
        session_id: The session ID
        prompt_number: Sequential prompt number within the session
        prompt_text: The user's prompt text
        embedding: Optional pre-computed embedding vector (768 dims)
        skip_memory_check: If True, bypass the memory enabled check

    Returns:
        The created prompt entry, or None if memory is disabled
    """
    if not skip_memory_check and not is_memory_feature_enabled(project_id, "user_prompts"):
        logger.debug(f"User prompts disabled for {project_id}, skipping")
        return None

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO user_prompts
                (project_id, session_id, prompt_number, prompt_text, embedding)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (session_id, prompt_number) DO UPDATE
            SET prompt_text = EXCLUDED.prompt_text,
                embedding = EXCLUDED.embedding
            RETURNING {PROMPT_COLUMNS}
            """,
            (
                project_id,
                session_id,
                prompt_number,
                prompt_text,
                embedding,
            ),
        )
        row = cur.fetchone()
        conn.commit()

        if row:
            logger.info(f"Created user prompt {session_id}:{prompt_number} for {project_id}")
            return _row_to_dict(row)
        return None


def get_user_prompt(prompt_id: str | UUID) -> dict[str, Any] | None:
    """Get a user prompt by ID.

    Args:
        prompt_id: The prompt UUID

    Returns:
        The prompt entry or None if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {PROMPT_COLUMNS}
            FROM user_prompts
            WHERE id = %s
            """,
            (str(prompt_id),),
        )
        row = cur.fetchone()
        return _row_to_dict(row) if row else None


def list_user_prompts(
    project_id: str,
    session_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List user prompts for a project.

    Args:
        project_id: The project ID
        session_id: Optional session ID to filter by
        limit: Maximum number of results
        offset: Number of results to skip

    Returns:
        List of prompt entries
    """
    with get_connection() as conn, conn.cursor() as cur:
        if session_id:
            cur.execute(
                f"""
                SELECT {PROMPT_COLUMNS}
                FROM user_prompts
                WHERE project_id = %s AND session_id = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (project_id, session_id, limit, offset),
            )
        else:
            cur.execute(
                f"""
                SELECT {PROMPT_COLUMNS}
                FROM user_prompts
                WHERE project_id = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (project_id, limit, offset),
            )
        return [_row_to_dict(row) for row in cur.fetchall()]


def get_prompts_without_embeddings(
    project_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Get user prompts that don't have embeddings yet.

    Args:
        project_id: Optional project ID to filter by
        limit: Maximum number of results

    Returns:
        List of prompts needing embeddings
    """
    with get_connection() as conn, conn.cursor() as cur:
        if project_id:
            cur.execute(
                f"""
                SELECT {PROMPT_COLUMNS}
                FROM user_prompts
                WHERE embedding IS NULL AND project_id = %s
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (project_id, limit),
            )
        else:
            cur.execute(
                f"""
                SELECT {PROMPT_COLUMNS}
                FROM user_prompts
                WHERE embedding IS NULL
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (limit,),
            )
        return [_row_to_dict(row) for row in cur.fetchall()]


def update_prompt_embedding(
    prompt_id: str | UUID,
    embedding: list[float],
) -> bool:
    """Update the embedding for a user prompt.

    Args:
        prompt_id: The prompt UUID
        embedding: The embedding vector (768 dims)

    Returns:
        True if updated, False if not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE user_prompts
            SET embedding = %s
            WHERE id = %s
            """,
            (embedding, str(prompt_id)),
        )
        conn.commit()
        return cur.rowcount > 0


def bulk_update_prompt_embeddings(
    updates: list[tuple[str, list[float]]],
) -> int:
    """Bulk update embeddings for multiple prompts.

    Args:
        updates: List of (prompt_id, embedding) tuples

    Returns:
        Number of prompts updated
    """
    if not updates:
        return 0

    with get_connection() as conn, conn.cursor() as cur:
        # Use executemany for batch update
        cur.executemany(
            """
            UPDATE user_prompts
            SET embedding = %s
            WHERE id = %s
            """,
            [(embedding, prompt_id) for prompt_id, embedding in updates],
        )
        conn.commit()
        updated = cur.rowcount
        logger.info(f"Bulk updated {updated} prompt embeddings")
        return updated
