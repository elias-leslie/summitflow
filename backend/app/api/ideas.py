"""Ideas API endpoints.

Crowdsourced improvement ideas from game users.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from ..schemas.ideas import IdeaCreate, IdeaRetry
from ..services.ideas_helpers import check_rate_limit, extract_email_from_cf_jwt
from ..storage.ideas_repository import (
    create_idea_in_db,
    get_idea_by_id,
    get_idea_for_approval,
    get_idea_for_refinement,
    get_idea_for_retry,
    get_idea_list,
    update_idea_with_task,
    verify_project_exists,
)
from ..storage.tasks.core import create_task

router = APIRouter()
logger = logging.getLogger(__name__)

# Track last execution time per project for throttling
_last_execution: dict[str, datetime] = {}
EXECUTION_COOLDOWN_SECONDS = 300  # 5 minutes between manual executions


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
    user_identifier = user_email or x_forwarded_for or "anonymous"
    check_rate_limit(project_id, user_identifier)

    created_idea_id = create_idea_in_db(project_id, body.raw_text, user_email)

    # Auto-trigger refinement in background
    async def run_refinement() -> None:
        try:
            from ..services.idea_refiner import refine_idea, update_idea_with_refinement

            result = refine_idea(body.raw_text, project_id=project_id)
            update_idea_with_refinement(created_idea_id, result, project_id=project_id)
        except Exception as e:
            logger.error(f"Auto-refinement failed for {created_idea_id}: {e}")

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
    ideas = get_idea_list(project_id, status, limit, offset)
    return {"ideas": ideas, "limit": limit, "offset": offset}


@router.get("/projects/{project_id}/ideas/{idea_id}")
async def get_idea(project_id: str, idea_id: str) -> dict[str, Any]:
    """Get a specific idea."""
    return get_idea_by_id(project_id, idea_id)


@router.post("/projects/{project_id}/ideas/{idea_id}/refine")
async def refine_idea_endpoint(project_id: str, idea_id: str) -> dict[str, Any]:
    """Trigger AI refinement of an idea.

    Returns the refined result including category, complexity, and feasibility.
    """
    from ..services.idea_refiner import refine_idea, update_idea_with_refinement

    raw_text, _ = get_idea_for_refinement(project_id, idea_id)

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

    raw_text, retry_count = get_idea_for_retry(project_id, idea_id)

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
    idea_data = get_idea_for_approval(project_id, idea_id)

    # Create task from idea
    task_type = "bug" if idea_data["category"] == "bug" else "task"
    labels = ["crowdsourced"]
    if idea_data["user_email"]:
        labels.append(f"contributor:{idea_data['user_email']}")

    # Map idea complexity to task complexity
    complexity_map = {"simple": "SIMPLE", "medium": "STANDARD", "complex": "COMPLEX"}
    task_complexity = (
        complexity_map.get(idea_data["complexity"], "STANDARD")
        if idea_data["complexity"]
        else "STANDARD"
    )

    task = create_task(
        project_id=project_id,
        title=idea_data["refined_text"][:100] if idea_data["refined_text"] else "Crowdsourced idea",
        description=idea_data["refined_text"],
        task_type=task_type,
        priority=3,  # Lower priority for crowdsourced ideas
        complexity=task_complexity,
    )

    # Update idea with task link
    update_idea_with_task(idea_id, task["id"])

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
    verify_project_exists(project_id)

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
