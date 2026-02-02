"""Database operations for ideas."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from .connection import generate_prefixed_id, get_connection


def create_idea_in_db(project_id: str, raw_text: str, user_email: str | None) -> str:
    """Create a new idea in the database.

    Args:
        project_id: Project ID
        raw_text: Raw idea text
        user_email: User email (optional)

    Returns:
        Created idea ID

    Raises:
        HTTPException: If project not found or creation fails
    """
    with get_connection() as conn, conn.cursor() as cur:
        # Validate project exists
        cur.execute("SELECT 1 FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

        idea_id = generate_prefixed_id("idea")
        now = datetime.now(UTC)

        cur.execute(
            """
            INSERT INTO ideas (id, project_id, raw_text, user_email, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, 'pending_refinement', %s, %s)
            RETURNING id
            """,
            (idea_id, project_id, raw_text, user_email, now, now),
        )
        row = cur.fetchone()
        conn.commit()

        if not row:
            raise HTTPException(status_code=500, detail="Failed to create idea")

        return str(row[0])


def get_idea_list(
    project_id: str, status: str | None, limit: int, offset: int
) -> list[dict[str, Any]]:
    """Get list of ideas for a project.

    Args:
        project_id: Project ID
        status: Optional status filter
        limit: Number of results
        offset: Pagination offset

    Returns:
        List of idea dictionaries
    """
    with get_connection() as conn, conn.cursor() as cur:
        base_query = "SELECT id, raw_text, refined_text, user_email, status, category, complexity, priority_score, created_at FROM ideas WHERE project_id = %s"
        params: list[Any] = [project_id]

        if status:
            base_query += " AND status = %s"
            params.append(status)

        base_query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        cur.execute(base_query, params)
        rows = cur.fetchall()

    return [
        {
            "id": row[0],
            "raw_text": row[1],
            "refined_text": row[2],
            "user_email": row[3],
            "status": row[4],
            "category": row[5],
            "complexity": row[6],
            "priority_score": row[7],
            "created_at": row[8].isoformat() if row[8] else None,
        }
        for row in rows
    ]


def get_idea_by_id(project_id: str, idea_id: str) -> dict[str, Any]:
    """Get a specific idea by ID.

    Args:
        project_id: Project ID
        idea_id: Idea ID

    Returns:
        Idea dictionary

    Raises:
        HTTPException: If idea not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, raw_text, refined_text, user_email, status,
                   category, complexity, feasibility_score, rejection_reason,
                   retry_count, ease_score, impact_score, priority_score,
                   task_id, created_at, updated_at, approved_at, completed_at
            FROM ideas WHERE id = %s AND project_id = %s
            """,
            (idea_id, project_id),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Idea not found")

    return {
        "id": row[0],
        "project_id": row[1],
        "raw_text": row[2],
        "refined_text": row[3],
        "user_email": row[4],
        "status": row[5],
        "category": row[6],
        "complexity": row[7],
        "feasibility_score": row[8],
        "rejection_reason": row[9],
        "retry_count": row[10],
        "ease_score": row[11],
        "impact_score": row[12],
        "priority_score": row[13],
        "task_id": row[14],
        "created_at": row[15].isoformat() if row[15] else None,
        "updated_at": row[16].isoformat() if row[16] else None,
        "approved_at": row[17].isoformat() if row[17] else None,
        "completed_at": row[18].isoformat() if row[18] else None,
    }


def get_idea_for_refinement(project_id: str, idea_id: str) -> tuple[str, str]:
    """Get idea data for refinement.

    Args:
        project_id: Project ID
        idea_id: Idea ID

    Returns:
        Tuple of (raw_text, status)

    Raises:
        HTTPException: If idea not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT raw_text, status FROM ideas WHERE id = %s AND project_id = %s",
            (idea_id, project_id),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Idea not found")

    return row[0], row[1]


def get_idea_for_retry(project_id: str, idea_id: str) -> tuple[str, int]:
    """Get idea data for retry.

    Args:
        project_id: Project ID
        idea_id: Idea ID

    Returns:
        Tuple of (raw_text, retry_count)

    Raises:
        HTTPException: If idea not found or retry limit reached
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT raw_text, retry_count FROM ideas WHERE id = %s AND project_id = %s",
            (idea_id, project_id),
        )
        row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Idea not found")

        raw_text, retry_count = row[0], row[1]

        if retry_count >= 3:
            raise HTTPException(
                status_code=429,
                detail="Retry limit reached (3 retries maximum)",
            )

        # Increment retry count
        cur.execute(
            "UPDATE ideas SET retry_count = retry_count + 1 WHERE id = %s",
            (idea_id,),
        )
        conn.commit()

        return raw_text, retry_count


def get_idea_for_approval(project_id: str, idea_id: str) -> dict[str, Any]:
    """Get idea data for approval.

    Args:
        project_id: Project ID
        idea_id: Idea ID

    Returns:
        Dict with refined_text, category, complexity, status, user_email

    Raises:
        HTTPException: If idea not found or cannot be approved
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT refined_text, category, complexity, status, user_email
            FROM ideas WHERE id = %s AND project_id = %s
            """,
            (idea_id, project_id),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Idea not found")

    status = row[3]
    if status == "rejected":
        raise HTTPException(status_code=400, detail="Cannot approve a rejected idea")
    if status == "approved":
        raise HTTPException(status_code=400, detail="Idea already approved")

    return {
        "refined_text": row[0],
        "category": row[1],
        "complexity": row[2],
        "status": row[3],
        "user_email": row[4],
    }


def update_idea_with_task(idea_id: str, task_id: str) -> None:
    """Update idea with linked task ID.

    Args:
        idea_id: Idea ID
        task_id: Task ID to link
    """
    now = datetime.now(UTC)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ideas SET
                status = 'approved',
                task_id = %s,
                approved_at = %s,
                updated_at = %s
            WHERE id = %s
            """,
            (task_id, now, now, idea_id),
        )
        conn.commit()


def verify_project_exists(project_id: str) -> None:
    """Verify that a project exists.

    Args:
        project_id: Project ID

    Raises:
        HTTPException: If project not found
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Project not found")
