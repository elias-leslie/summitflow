"""Tasks API - Subtask management.

Handles:
- get_task_subtasks
- update_task_subtask
- delete_task_subtask
- create_subtask_endpoint
- create_subtasks_batch
- cleanup_prompt_endpoint
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ...logging_config import get_logger
from ...schemas.tasks import (
    CitationAcknowledgeRequest,
    CitationAcknowledgeResponse,
    CitationLogRequest,
    CitationLogResponse,
    CleanupPromptRequest,
    CleanupPromptResponse,
    SubtaskCreate,
    SubtaskResponse,
    SubtaskUpdate,
)
from .core import _get_task_or_404, _verify_task_project

logger = get_logger(__name__)

router = APIRouter()


@router.get(
    "/projects/{project_id}/tasks/{task_id}/subtasks",
    response_model=dict[str, Any],
)
async def get_task_subtasks(
    project_id: str,
    task_id: str,
    include_steps: bool = Query(False, description="Include steps from table for each subtask"),
) -> dict[str, Any]:
    """Get subtasks for a task.

    Args:
        project_id: Project ID
        task_id: Task ID
        include_steps: If True, include steps from task_subtask_steps table

    Returns:
        Dict with subtasks list and summary
    """
    _verify_task_project(task_id, project_id)

    from ...storage.subtasks import get_subtask_summary, get_subtasks_for_task

    subtasks = get_subtasks_for_task(task_id, include_steps=include_steps)
    summary = get_subtask_summary(task_id)

    return {
        "subtasks": subtasks,
        "summary": summary,
    }


@router.patch(
    "/projects/{project_id}/tasks/{task_id}/subtasks/{subtask_id}",
    response_model=SubtaskResponse,
)
async def update_task_subtask(
    project_id: str,
    task_id: str,
    subtask_id: str,
    request: SubtaskUpdate,
) -> SubtaskResponse:
    """Update a subtask's passes status.

    Args:
        project_id: Project ID
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "1.1")
        request: Update with passes boolean

    Returns:
        Updated SubtaskResponse
    """
    _verify_task_project(task_id, project_id)

    from ...storage.subtasks import (
        SubtaskGateError,
        update_subtask_passes,
    )

    try:
        updated = update_subtask_passes(task_id, subtask_id, request.passes)
    except SubtaskGateError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(e),
                "incomplete_steps": e.incomplete_steps,
            },
        ) from e

    if updated is None:
        raise HTTPException(
            status_code=404,
            detail=f"Subtask {subtask_id} not found for task {task_id}",
        )

    # Add steps field if not present (update_subtask_passes doesn't fetch steps)
    if "steps" not in updated:
        updated["steps"] = []

    return SubtaskResponse(**updated)


@router.delete("/projects/{project_id}/tasks/{task_id}/subtasks/{subtask_id}")
async def delete_task_subtask(
    project_id: str,
    task_id: str,
    subtask_id: str,
) -> dict[str, Any]:
    """Delete a subtask and all its steps.

    Args:
        project_id: Project ID
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "99.1")

    Returns:
        Deletion confirmation with details.
    """
    _verify_task_project(task_id, project_id)

    from ...storage.subtasks import delete_subtask

    deleted = delete_subtask(task_id, subtask_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Subtask {subtask_id} not found for task {task_id}",
        )

    return {
        "status": "deleted",
        "project_id": project_id,
        "task_id": task_id,
        "subtask_id": subtask_id,
    }


@router.post(
    "/projects/{project_id}/tasks/{task_id}/subtasks",
    response_model=SubtaskResponse,
    status_code=201,
)
async def create_subtask_endpoint(
    project_id: str,
    task_id: str,
    request: SubtaskCreate,
) -> SubtaskResponse:
    """Create a single subtask for a task.

    Args:
        project_id: Project ID
        task_id: Task ID
        request: Subtask creation data

    Returns:
        Created SubtaskResponse
    """
    _verify_task_project(task_id, project_id)

    from ...storage.subtasks import create_subtask

    # Convert StepInput objects to dicts for storage layer
    steps: list[str | dict[str, Any]] = []
    for step in request.steps:
        if isinstance(step, str):
            steps.append(step)
        else:
            step_dict: dict[str, Any] = {"description": step.description}
            if step.spec:
                step_dict["spec"] = step.spec
            if step.verify_command:
                step_dict["verify_command"] = step.verify_command
            if step.expected_output:
                step_dict["expected_output"] = step.expected_output
            steps.append(step_dict)

    subtask = create_subtask(
        task_id=task_id,
        subtask_id=request.subtask_id,
        description=request.description,
        display_order=request.display_order,
        phase=request.phase,
        steps=steps,
        details=request.details,
    )

    # Convert steps (list of dicts) to steps (list of strings) for response
    if subtask.get("steps") and isinstance(subtask["steps"][0], dict):
        subtask["steps"] = [s["description"] for s in subtask["steps"]]
    elif "steps" not in subtask:
        subtask["steps"] = []

    return SubtaskResponse(**subtask)


@router.post(
    "/projects/{project_id}/tasks/{task_id}/subtasks/batch",
    response_model=dict[str, Any],
    status_code=201,
)
async def create_subtasks_batch(
    project_id: str,
    task_id: str,
    request: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Create multiple subtasks for a task in batch.

    Args:
        project_id: Project ID
        task_id: Task ID
        request: {"items": [subtask_data_list]}

    Returns:
        {"created": list of created subtasks}
    """
    _verify_task_project(task_id, project_id)

    from ...storage.subtasks import bulk_create_subtasks

    items = request.get("items", [])
    if not items:
        return {"created": []}

    created = bulk_create_subtasks(task_id, items)

    return {"created": created}


@router.post(
    "/projects/{project_id}/tasks/cleanup-prompt",
    response_model=CleanupPromptResponse,
)
async def cleanup_prompt_endpoint(
    project_id: str,
    request: CleanupPromptRequest,
) -> CleanupPromptResponse:
    """Clean up and refine a raw prompt using AI.

    Uses Gemini Flash for fast, cheap text cleanup.

    Args:
        project_id: Project ID
        request: Request with raw_request text

    Returns:
        CleanupPromptResponse with cleaned text and changes list
    """
    try:
        from ...services.agent_hub_client import AgentHubLLMClient

        client = AgentHubLLMClient(agent_slug="analyst")
        if not client.is_available():
            # Return unchanged if Gemini unavailable
            return CleanupPromptResponse(
                cleaned_prompt=request.raw_request,
                changes_made=["Gemini unavailable - no changes made"],
            )

        prompt = f"""Clean up and refine this task request. Fix grammar, clarify intent, and expand abbreviations. Keep the meaning unchanged.

Original:
{request.raw_request}

Return JSON:
{{"cleaned_prompt": "...", "changes_made": ["change1", "change2"]}}"""

        response = client.generate(prompt, temperature=0.2)

        import json

        text = response.content.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]

        data = json.loads(text.strip())

        return CleanupPromptResponse(
            cleaned_prompt=data.get("cleaned_prompt", request.raw_request),
            changes_made=data.get("changes_made", []),
        )

    except Exception as e:
        logger.warning("Cleanup prompt failed: %s", e)  # type: ignore[call-arg]
        return CleanupPromptResponse(
            cleaned_prompt=request.raw_request,
            changes_made=[f"Cleanup failed: {e}"],
        )


# Global endpoints (no project_id required - task IDs are globally unique)


@router.get(
    "/tasks/{task_id}/subtasks",
    response_model=dict[str, Any],
)
async def get_task_subtasks_global(
    task_id: str,
    include_steps: bool = Query(False, description="Include steps for each subtask"),
) -> dict[str, Any]:
    """Get subtasks for a task (global lookup, no project context required).

    Task IDs are globally unique, so project_id is not needed.

    Args:
        task_id: Task ID
        include_steps: If True, include steps for each subtask

    Returns:
        Dict with subtasks list and summary
    """
    _get_task_or_404(task_id)

    from ...storage.subtasks import get_subtask_summary, get_subtasks_for_task

    subtasks = get_subtasks_for_task(task_id, include_steps=include_steps)
    summary = get_subtask_summary(task_id)

    return {
        "subtasks": subtasks,
        "summary": summary,
    }


@router.patch(
    "/tasks/{task_id}/subtasks/{subtask_id}",
    response_model=SubtaskResponse,
)
async def update_task_subtask_global(
    task_id: str,
    subtask_id: str,
    request: SubtaskUpdate,
) -> SubtaskResponse:
    """Update a subtask's passes status (global lookup, no project context required).

    Args:
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "1.1")
        request: Update with passes boolean

    Returns:
        Updated SubtaskResponse
    """
    _get_task_or_404(task_id)

    from ...storage.subtasks import (
        SubtaskGateError,
        update_subtask_passes,
    )

    try:
        updated = update_subtask_passes(task_id, subtask_id, request.passes)
    except SubtaskGateError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(e),
                "incomplete_steps": e.incomplete_steps,
            },
        ) from e

    if updated is None:
        raise HTTPException(
            status_code=404,
            detail=f"Subtask {subtask_id} not found for task {task_id}",
        )

    if "steps" not in updated:
        updated["steps"] = []

    return SubtaskResponse(**updated)


@router.post(
    "/tasks/{task_id}/subtasks/{subtask_id}/citations",
    response_model=CitationLogResponse,
)
async def log_subtask_citations(
    task_id: str,
    subtask_id: str,
    request: CitationLogRequest,
) -> CitationLogResponse:
    """Log episode citations for a subtask with suffix notation ratings.

    Citations use suffix notation for three-signal rating:
    - M:abc123+  -> mandate helpful (promotes episode tier)
    - G:def456-  -> guardrail harmful (demotes/blacklists episode)
    - M:xyz789   -> used/neutral (no suffix, just records usage)

    Args:
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "1.1")
        request: CitationLogRequest with list of citations

    Returns:
        CitationLogResponse with count of logged citations
    """
    _get_task_or_404(task_id)

    from ...storage.subtasks import log_citations

    logged = log_citations(task_id, subtask_id, request.citations)

    return CitationLogResponse(
        logged=logged,
        subtask_id=subtask_id,
    )


@router.post(
    "/tasks/{task_id}/subtasks/{subtask_id}/citations/acknowledge-none",
    response_model=CitationAcknowledgeResponse,
)
async def acknowledge_no_citations(
    task_id: str,
    subtask_id: str,
    request: CitationAcknowledgeRequest,
) -> CitationAcknowledgeResponse:
    """Acknowledge that no memories were needed for this subtask.

    Requires {"honestly_none": true} body to create friction that makes
    the agent reflect before claiming no memories were helpful.

    Args:
        task_id: Task ID
        subtask_id: Subtask ID (e.g., "1.1")
        request: CitationAcknowledgeRequest with honestly_none=true

    Returns:
        CitationAcknowledgeResponse with acknowledgment status
    """
    _get_task_or_404(task_id)

    from ...storage.subtasks import acknowledge_no_citations

    acknowledged = acknowledge_no_citations(task_id, subtask_id)

    return CitationAcknowledgeResponse(
        acknowledged=acknowledged,
        subtask_id=subtask_id,
    )
