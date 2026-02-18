"""Tasks API - AI enrichment and discussion.

Handles:
- enrich_task_endpoint
- discuss_task_endpoint
- accept_task_endpoint
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...logging_config import get_logger
from ...schemas.tasks import (
    DiscussionMessage,
    DiscussionRequest,
    DiscussionResponse,
    EnrichmentRequest,
    EnrichmentResponse,
    TaskResponse,
)
from ...storage import tasks as task_store
from .helpers import verify_task_project
from .response import task_to_response

logger = get_logger(__name__)

router = APIRouter()


@router.post(
    "/projects/{project_id}/tasks/enrich",
    response_model=EnrichmentResponse,
    status_code=202,
)
async def enrich_task_endpoint(
    project_id: str,
    request: EnrichmentRequest,
    sync: bool = Query(default=False, description="Run enrichment synchronously"),
) -> EnrichmentResponse:
    """Create a task and trigger AI enrichment.

    Args:
        project_id: Project ID
        request: Enrichment request with raw_request text
        sync: If true, run enrichment inline (slower but returns enriched task)

    Returns:
        EnrichmentResponse with task_id and status
    """
    # Create task in draft state
    task = task_store.create_task(
        project_id=project_id,
        title=request.raw_request[:100] + ("..." if len(request.raw_request) > 100 else ""),
        raw_request=request.raw_request,
        enrichment_status="enriching" if not sync else "draft",
        priority=request.priority or 2,
        task_type=request.task_type or "task",
    )

    if sync:
        # Run enrichment synchronously
        try:
            from ...services.enrichment_service import apply_enrichment_to_task, enrich_and_validate

            enriched, _validation = enrich_and_validate(
                project_id=project_id,
                task_id=task["id"],
                raw_request=request.raw_request,
            )
            apply_enrichment_to_task(task["id"], enriched)

            return EnrichmentResponse(
                task_id=task["id"],
                enrichment_status="review",
                message="Task enriched successfully. Ready for review.",
            )
        except Exception as e:
            logger.error("sync_enrichment_failed", error=str(e))
            task_store.update_task(task["id"], enrichment_status="failed")
            raise HTTPException(status_code=500, detail=f"Enrichment failed: {e}") from None
    else:
        # Queue for async enrichment via Hatchet
        try:
            from ...workflows.models import EnrichInput
            from ...workflows.utility import enrich_wf

            await enrich_wf.aio_run_no_wait(
                EnrichInput(
                    project_id=project_id,
                    task_id=task["id"],
                    raw_request=request.raw_request,
                )
            )
        except Exception as e:
            logger.warning("enrichment_queue_failed", error=str(e))
            # Still return - we can retry later

        return EnrichmentResponse(
            task_id=task["id"],
            enrichment_status="enriching",
            message="Task created and enrichment queued.",
        )


@router.post(
    "/projects/{project_id}/tasks/{task_id}/discuss",
    response_model=DiscussionResponse,
)
async def discuss_task_endpoint(
    project_id: str,
    task_id: str,
    request: DiscussionRequest,
) -> DiscussionResponse:
    """Have a discussion about a task with AI.

    Args:
        project_id: Project ID
        task_id: Task ID to discuss
        request: Discussion request with message

    Returns:
        DiscussionResponse with AI reply and any updates
    """
    task = verify_task_project(task_id, project_id)

    from ...services.enrichment_service import apply_discussion_changes, discuss_task

    # Get discussion history from task metadata (if any)
    history: list[dict[str, str]] = []
    plan_content = task.get("plan_content") or {}
    if "discussion_history" in plan_content:
        history = plan_content["discussion_history"]

    # Run discussion
    result = discuss_task(
        project_id=project_id,
        task_id=task_id,
        message=request.message,
        history=history,
        current_task=task,
    )

    # Update history
    history.append({"role": "user", "content": request.message})
    history.append({"role": "assistant", "content": result.response})

    # Apply changes if any
    updated_task = task
    if result.updated_task:
        updated_task = apply_discussion_changes(task_id, result.updated_task)

    # Store updated history
    plan_content["discussion_history"] = history
    task_store.update_task(task_id, plan_content=plan_content)

    # Update enrichment status if first message
    if task.get("enrichment_status") == "review":
        task_store.update_task(task_id, enrichment_status="discussing")

    return DiscussionResponse(
        response=result.response,
        updated_task=task_to_response(updated_task) if result.updated_task else None,
        history=[
            DiscussionMessage(
                role=h["role"],  # str from DB narrowed to Literal
                content=h["content"],
                timestamp="",
            )
            for h in history
        ],
    )


@router.post(
    "/projects/{project_id}/tasks/{task_id}/accept",
    response_model=TaskResponse,
)
async def accept_task_endpoint(
    project_id: str,
    task_id: str,
) -> TaskResponse:
    """Accept an enriched task and mark it ready for execution.

    Args:
        project_id: Project ID
        task_id: Task ID to accept

    Returns:
        Updated TaskResponse
    """
    task = verify_task_project(task_id, project_id)

    # Verify task is in acceptable state
    current_status = task.get("enrichment_status")
    if current_status not in ("review", "discussing"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot accept task with enrichment_status '{current_status}'. Must be 'review' or 'discussing'.",
        )

    # Update task
    updated = task_store.update_task(
        task_id,
        enrichment_status="accepted",
        status="pending",  # Ready for execution
    )

    if updated is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    return task_to_response(updated)
