"""Tasks API - Subtask citation endpoints.

Handles citation logging and acknowledgment for subtasks.
"""

from __future__ import annotations

from fastapi import APIRouter

from ...schemas.tasks import (
    CitationAcknowledgeRequest,
    CitationAcknowledgeResponse,
    CitationLogRequest,
    CitationLogResponse,
)
from .helpers import get_task_or_404

router = APIRouter()


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
    get_task_or_404(task_id)

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
    get_task_or_404(task_id)

    from ...storage.subtasks import acknowledge_no_citations

    acknowledged = acknowledge_no_citations(task_id, subtask_id)

    return CitationAcknowledgeResponse(
        acknowledged=acknowledged,
        subtask_id=subtask_id,
    )
