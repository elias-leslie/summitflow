"""Ideas API endpoints.

Crowdsourced improvement ideas from game users.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from ..storage.connection import generate_prefixed_id, get_connection

router = APIRouter()

# Rate limiting constants
MAX_IDEAS_PER_USER_PER_HOUR = 5
ESTIMATED_COST_PER_REFINEMENT = 0.002  # ~$0.002 for Gemini Flash (refine + score)
DEFAULT_DAILY_BUDGET_USD = 5.0


def get_project_daily_budget(project_id: str) -> float:
    """Get the daily budget for a project from automation settings."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT automation_settings FROM projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()
        if row and row[0]:
            return float(row[0].get("daily_budget_usd", DEFAULT_DAILY_BUDGET_USD))
        return DEFAULT_DAILY_BUDGET_USD


def check_rate_limit(project_id: str, user_identifier: str) -> None:
    """Check if user/project has exceeded rate limits.

    Uses project's daily_budget_usd from automation settings.
    Raises HTTPException 429 if limits exceeded.
    """
    now = datetime.now(UTC)
    hour_ago = now - timedelta(hours=1)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    with get_connection() as conn, conn.cursor() as cur:
        # Check per-user hourly limit (only for identified users)
        if user_identifier and user_identifier != "anonymous":
            cur.execute(
                """
                SELECT COUNT(*) FROM ideas
                WHERE user_email = %s
                AND created_at > %s
                AND project_id = %s
                """,
                (user_identifier, hour_ago, project_id),
            )
            row = cur.fetchone()
            user_count = row[0] if row else 0

            if user_count >= MAX_IDEAS_PER_USER_PER_HOUR:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Maximum {MAX_IDEAS_PER_USER_PER_HOUR} ideas per hour.",
                )

        # Check project daily budget
        # Count today's refinements and compare against budget
        cur.execute(
            """
            SELECT COUNT(*) FROM ideas
            WHERE project_id = %s
            AND created_at > %s
            AND status IN ('refined', 'approved', 'rejected', 'executing', 'completed')
            """,
            (project_id, day_start),
        )
        row = cur.fetchone()
        daily_refinements = row[0] if row else 0

    # Calculate cost and check against budget
    daily_cost = daily_refinements * ESTIMATED_COST_PER_REFINEMENT
    daily_budget = get_project_daily_budget(project_id)

    if daily_cost >= daily_budget:
        raise HTTPException(
            status_code=429,
            detail=f"Daily budget exhausted (${daily_cost:.2f}/${daily_budget:.2f}). Try again tomorrow.",
        )


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
    x_forwarded_for: str | None = Header(None, alias="X-Forwarded-For"),
) -> dict[str, Any]:
    """Submit a new improvement idea.

    Extracts user email from Cloudflare Access JWT for attribution.
    Rate limited to prevent abuse.
    Returns idea_id for frontend tracking.
    """
    user_email = extract_email_from_cf_jwt(cf_access_jwt)

    # Use email for rate limiting, fallback to IP
    user_identifier = user_email or x_forwarded_for or "anonymous"
    check_rate_limit(project_id, user_identifier)

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

    created_idea_id = row[0]

    # Auto-trigger refinement in background
    import asyncio

    from ..services.idea_refiner import refine_idea, update_idea_with_refinement

    async def run_refinement() -> None:
        try:
            result = refine_idea(body.raw_text, project_id=project_id)
            update_idea_with_refinement(created_idea_id, result, project_id=project_id)
        except Exception as e:
            # Log but don't fail - idea is created, refinement can be retried
            import logging

            logging.getLogger(__name__).error(f"Auto-refinement failed for {created_idea_id}: {e}")

    # Fire and forget - don't block the response
    _task = asyncio.create_task(run_refinement())  # noqa: RUF006

    return {"idea_id": created_idea_id, "status": "pending_refinement"}


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


@router.post("/projects/{project_id}/ideas/{idea_id}/refine")
async def refine_idea_endpoint(project_id: str, idea_id: str) -> dict[str, Any]:
    """Trigger AI refinement of an idea.

    Returns the refined result including category, complexity, and feasibility.
    """
    from ..services.idea_refiner import refine_idea, update_idea_with_refinement

    # Get idea
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT raw_text, status FROM ideas WHERE id = %s AND project_id = %s",
            (idea_id, project_id),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Idea not found")

    raw_text = row[0]

    # Run AI refinement
    result = refine_idea(raw_text, project_id=project_id)
    update_idea_with_refinement(idea_id, result, project_id=project_id)

    return {
        "idea_id": idea_id,
        "refined_text": result.refined_text,
        "category": result.category,
        "complexity": result.complexity,
        "feasibility_score": result.feasibility_score,
        "rejection_reason": result.rejection_reason,
        "status": "rejected" if result.rejection_reason else "refined",
    }


@router.post("/projects/{project_id}/ideas/{idea_id}/retry")
async def retry_refinement(project_id: str, idea_id: str, body: IdeaRetry) -> dict[str, Any]:
    """Retry AI refinement with additional context.

    Limited to 3 retries per idea. Returns 429 if limit exceeded.
    """
    from ..services.idea_refiner import refine_idea, update_idea_with_refinement

    # Get idea and check retry count
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT raw_text, retry_count FROM ideas WHERE id = %s AND project_id = %s",
            (idea_id, project_id),
        )
        row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Idea not found")

        raw_text = row[0]
        retry_count = row[1]

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

    # Run AI refinement with additional context
    result = refine_idea(raw_text, body.additional_context, project_id=project_id)
    update_idea_with_refinement(idea_id, result, project_id=project_id)

    return {
        "idea_id": idea_id,
        "refined_text": result.refined_text,
        "category": result.category,
        "complexity": result.complexity,
        "feasibility_score": result.feasibility_score,
        "rejection_reason": result.rejection_reason,
        "status": "rejected" if result.rejection_reason else "refined",
        "retry_count": retry_count + 1,
        "retries_remaining": 2 - retry_count,
    }


@router.post("/projects/{project_id}/ideas/{idea_id}/approve")
async def approve_idea(project_id: str, idea_id: str) -> dict[str, Any]:
    """Approve an idea and create a task from it.

    Creates a new task in SummitFlow with the refined idea as description.
    Links the task back to the idea for tracking.
    """
    from ..storage.tasks.core import create_task

    # Get idea
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

    refined_text = row[0]
    category = row[1]
    complexity = row[2]
    status = row[3]
    user_email = row[4]

    if status == "rejected":
        raise HTTPException(status_code=400, detail="Cannot approve a rejected idea")
    if status == "approved":
        raise HTTPException(status_code=400, detail="Idea already approved")

    # Create task from idea
    task_type = "bug" if category == "bug" else "task"
    labels = ["crowdsourced"]
    if user_email:
        labels.append(f"contributor:{user_email}")

    # Map idea complexity to task complexity (simple->SIMPLE, medium->STANDARD, complex->COMPLEX)
    complexity_map = {"simple": "SIMPLE", "medium": "STANDARD", "complex": "COMPLEX"}
    task_complexity = complexity_map.get(complexity, "STANDARD") if complexity else "STANDARD"

    task = create_task(
        project_id=project_id,
        title=refined_text[:100] if refined_text else "Crowdsourced idea",
        description=refined_text,
        task_type=task_type,
        labels=labels,
        priority=3,  # Lower priority for crowdsourced ideas
        complexity=task_complexity,
    )

    # Update idea with task link
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
            (task["id"], now, now, idea_id),
        )
        conn.commit()

    return {
        "idea_id": idea_id,
        "task_id": task["id"],
        "status": "approved",
    }


@router.get("/notifications")
def get_user_notifications(
    user_email: str = Query(..., description="User email to fetch notifications for"),
    mark_as_seen: bool = Query(True, description="Whether to mark notifications as read"),
    cf_access_jwt: str | None = Header(None, alias="CF-Access-JWT-Assertion"),
) -> list[dict[str, Any]]:
    """Get notifications for a user by email.

    This endpoint is used by game clients to fetch user-specific notifications,
    such as when their crowdsourced idea has been implemented.

    The notifications are automatically marked as read when fetched (default behavior).
    """
    from ..storage.notifications import get_notifications_by_user_email

    # Optional: verify the requesting user matches the email (security)
    # For now, we allow any authenticated user to check any email
    # In production, you might want to verify cf_access_jwt matches user_email

    return get_notifications_by_user_email(
        user_email=user_email,
        status_filter="pending",
        mark_as_seen=mark_as_seen,
    )


# Track last execution time per project for throttling
_last_execution: dict[str, datetime] = {}
EXECUTION_COOLDOWN_SECONDS = 300  # 5 minutes between manual executions


@router.post("/projects/{project_id}/ideas/execute-now")
def execute_ideas_now(
    project_id: str,
) -> dict[str, Any]:
    """Manually trigger immediate execution of approved ideas.

    This is a testing/admin endpoint that triggers the crowdsourced
    idea processing task immediately instead of waiting for the
    scheduled nightly run.

    Throttled to prevent abuse (max once per 5 minutes per project).

    Returns:
        Dict with task_id for tracking execution status
    """
    from ..tasks.autonomous.ideas import process_crowdsourced_ideas

    # Check throttle
    last_exec = _last_execution.get(project_id)
    if last_exec:
        elapsed = (datetime.now(UTC) - last_exec).total_seconds()
        if elapsed < EXECUTION_COOLDOWN_SECONDS:
            remaining = int(EXECUTION_COOLDOWN_SECONDS - elapsed)
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests. Please wait {remaining} seconds.",
            )

    # Verify project exists
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Project not found")

    # Record execution time
    _last_execution[project_id] = datetime.now(UTC)

    # Dispatch async task
    task = process_crowdsourced_ideas.delay(project_id)

    return {
        "status": "dispatched",
        "task_id": task.id,
        "project_id": project_id,
        "message": f"Crowdsourced idea processing started for {project_id}",
    }
