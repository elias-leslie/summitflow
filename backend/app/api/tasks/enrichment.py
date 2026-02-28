"""Tasks API - AI enrichment and discussion."""

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


async def _run_sync_enrichment(project_id: str, task_id: str, raw_request: str) -> EnrichmentResponse:
    """Run enrichment synchronously and return response."""
    try:
        from ...services.enrichment_service import apply_enrichment_to_task, enrich_and_validate

        enriched, _validation = enrich_and_validate(
            project_id=project_id, task_id=task_id, raw_request=raw_request
        )
        apply_enrichment_to_task(task_id, enriched)
        return EnrichmentResponse(
            task_id=task_id,
            enrichment_status="review",
            message="Task enriched successfully. Ready for review.",
        )
    except Exception as e:
        logger.error("sync_enrichment_failed", error=str(e))
        task_store.update_task(task_id, enrichment_status="failed")
        raise HTTPException(status_code=500, detail=f"Enrichment failed: {e}") from None


async def _queue_async_enrichment(project_id: str, task_id: str, raw_request: str) -> EnrichmentResponse:
    """Queue task for async enrichment via Hatchet and return response."""
    try:
        from ...workflows.models import EnrichInput
        from ...workflows.utility import enrich_wf

        await enrich_wf.aio_run_no_wait(
            EnrichInput(project_id=project_id, task_id=task_id, raw_request=raw_request)
        )
    except Exception as e:
        logger.warning("enrichment_queue_failed", error=str(e))
    return EnrichmentResponse(
        task_id=task_id,
        enrichment_status="enriching",
        message="Task created and enrichment queued.",
    )


def _get_discussion_history(task: dict) -> list[dict[str, str]]:
    """Extract discussion history from task metadata.

    NOTE: Discussion history storage is not currently implemented.
    Returns empty list — callers build history from request/response pairs.
    """
    return []


def _save_discussion_history(task_id: str, task: dict, history: list[dict[str, str]]) -> None:
    """Persist updated discussion history and enrichment status to storage.

    NOTE: Discussion history persistence is not currently implemented.
    Only updates enrichment_status.
    """
    if task.get("enrichment_status") == "review":
        task_store.update_task(task_id, enrichment_status="discussing")


@router.post("/projects/{project_id}/tasks/enrich", response_model=EnrichmentResponse, status_code=202)
async def enrich_task_endpoint(
    project_id: str,
    request: EnrichmentRequest,
    sync: bool = Query(default=False, description="Run enrichment synchronously"),
) -> EnrichmentResponse:
    """Create a task and trigger AI enrichment."""
    task = task_store.create_task(
        project_id=project_id,
        title=request.raw_request[:100] + ("..." if len(request.raw_request) > 100 else ""),
        raw_request=request.raw_request,
        enrichment_status="enriching" if not sync else "draft",
        priority=request.priority or 2,
        task_type=request.task_type or "task",
    )
    if sync:
        return await _run_sync_enrichment(project_id, task["id"], request.raw_request)
    return await _queue_async_enrichment(project_id, task["id"], request.raw_request)


@router.post("/projects/{project_id}/tasks/{task_id}/discuss", response_model=DiscussionResponse)
async def discuss_task_endpoint(
    project_id: str, task_id: str, request: DiscussionRequest
) -> DiscussionResponse:
    """Have a discussion about a task with AI."""
    task = verify_task_project(task_id, project_id)
    from ...services.enrichment_service import apply_discussion_changes, discuss_task

    history = _get_discussion_history(task)
    result = discuss_task(
        project_id=project_id, task_id=task_id,
        message=request.message, history=history, current_task=task,
    )
    history.append({"role": "user", "content": request.message})
    history.append({"role": "assistant", "content": result.response})
    updated_task = apply_discussion_changes(task_id, result.updated_task) if result.updated_task else task
    _save_discussion_history(task_id, task, history)
    return DiscussionResponse(
        response=result.response,
        updated_task=task_to_response(updated_task) if result.updated_task else None,
        history=[DiscussionMessage(role=h["role"], content=h["content"], timestamp="") for h in history],
    )


@router.post("/projects/{project_id}/tasks/{task_id}/accept", response_model=TaskResponse)
async def accept_task_endpoint(project_id: str, task_id: str) -> TaskResponse:
    """Accept an enriched task and mark it ready for execution."""
    task = verify_task_project(task_id, project_id)
    current_status = task.get("enrichment_status")
    if current_status not in ("review", "discussing"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot accept task with enrichment_status '{current_status}'. Must be 'review' or 'discussing'.",
        )
    updated = task_store.update_task(task_id, enrichment_status="accepted", status="pending")
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return task_to_response(updated)
