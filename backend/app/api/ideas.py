"""Ideas API endpoints.

Crowdsourced improvement ideas from game users.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from ..storage.connection import generate_prefixed_id, get_connection

router = APIRouter()


class IdeaCreate(BaseModel):
    """Request body for submitting an idea."""

    raw_text: str


class IdeaRetry(BaseModel):
    """Request body for retrying refinement."""

    additional_context: str | None = None


def extract_email_from_cf_jwt(jwt_assertion: str | None) -> str | None:
    """Extract email from Cloudflare Access JWT.

    CF Access JWT is base64 encoded with 3 parts: header.payload.signature
    Payload contains 'email' field.
    """
    if not jwt_assertion:
        return None
    try:
        parts = jwt_assertion.split(".")
        if len(parts) != 3:
            return None
        # Add padding if needed
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding
        decoded = base64.urlsafe_b64decode(payload)
        data = json.loads(decoded)
        email = data.get("email")
        return str(email) if email is not None else None
    except Exception:
        return None


@router.post("/projects/{project_id}/ideas", status_code=201)
async def create_idea(
    project_id: str,
    body: IdeaCreate,
    cf_access_jwt: str | None = Header(None, alias="CF-Access-JWT-Assertion"),
) -> dict[str, Any]:
    """Submit a new improvement idea.

    Extracts user email from Cloudflare Access JWT for attribution.
    Returns idea_id for frontend tracking.
    """
    user_email = extract_email_from_cf_jwt(cf_access_jwt)

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
            (idea_id, project_id, body.raw_text, user_email, now, now),
        )
        row = cur.fetchone()
        conn.commit()

    if not row:
        raise HTTPException(status_code=500, detail="Failed to create idea")

    return {"idea_id": row[0], "status": "pending_refinement"}


@router.get("/projects/{project_id}/ideas")
async def list_ideas(
    project_id: str,
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List ideas for a project."""
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

    return {
        "ideas": [
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
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/projects/{project_id}/ideas/{idea_id}")
async def get_idea(project_id: str, idea_id: str) -> dict[str, Any]:
    """Get a specific idea."""
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
