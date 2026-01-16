"""Tasks API - Amendment management.

Handles:
- create_amendment_request: POST /criteria/{id}/amend
- list_amendments: GET /amendments
- approve_amendment: PATCH /amendments/{id}/approve
- reject_amendment: PATCH /amendments/{id}/reject
- get_amendment: GET /amendments/{id}
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...logging_config import get_logger
from ...storage.connection import get_connection
from .core import _verify_task_project

logger = get_logger(__name__)

router = APIRouter()


# Pydantic schemas for amendments
class AmendmentCreateRequest(BaseModel):
    """Request to create an amendment."""

    new_verify_command: str = Field(..., description="New verify_command to propose")
    reason: str = Field(..., description="Reason for the amendment")
    evidence: str | None = Field(None, description="Path to evidence artifact")


class AmendmentApproveRequest(BaseModel):
    """Request to approve an amendment."""

    approved_by: str = Field("human", description="Who is approving")
    reason: str | None = Field(None, description="Optional approval reason")


class AmendmentRejectRequest(BaseModel):
    """Request to reject an amendment."""

    rejected_by: str = Field("human", description="Who is rejecting")
    reason: str = Field(..., description="Required rejection reason")


@router.post(
    "/projects/{project_id}/tasks/{task_id}/criteria/{criterion_id}/amend",
    response_model=dict[str, Any],
    status_code=201,
)
async def create_amendment_request(
    project_id: str,
    task_id: str,
    criterion_id: str,
    request: AmendmentCreateRequest,
) -> dict[str, Any]:
    """Request an amendment to a locked criterion's verify_command.

    The new verify_command must fail preflight (TDD-style) to be valid.
    If it passes preflight, the amendment is rejected immediately.

    Workflow:
    1. Check criterion exists and is locked
    2. Run preflight on new command
    3. If preflight passes (exit 0): reject - would bypass verification
    4. If preflight fails normally (exit 1-125): create pending amendment
    5. If preflight crashes (exit 126-127): reject - syntax error

    Args:
        project_id: Project ID
        task_id: Task ID
        criterion_id: Criterion ID
        request: Amendment details with new_verify_command and reason

    Returns:
        Amendment result with id (if pending) or rejection reason.
    """
    _verify_task_project(task_id, project_id)

    from ...storage.amendments import create_amendment
    from ...storage.verification import get_task_criterion

    with get_connection() as conn:
        # Verify criterion exists
        criterion = get_task_criterion(conn, task_id, criterion_id)
        if not criterion:
            raise HTTPException(
                status_code=404,
                detail=f"Criterion {criterion_id} not found for task {task_id}",
            )

        # Create amendment (handles preflight validation internally)
        result = create_amendment(
            conn,
            task_id,
            criterion_id,
            request.new_verify_command,
            request.reason,
            request.evidence,
        )

    if "error" in result:
        # Could be: not locked, invalid pass, invalid crash
        status_code = 400 if result.get("status") == "rejected" else 422
        raise HTTPException(status_code=status_code, detail=result)

    return result


@router.get(
    "/projects/{project_id}/amendments",
    response_model=list[dict[str, Any]],
)
async def list_amendments_endpoint(
    project_id: str,
    task_id: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List amendments with optional filters.

    Args:
        project_id: Project ID (for validation)
        task_id: Filter by task ID
        status: Filter by status (pending, approved, rejected)

    Returns:
        List of amendment summaries.
    """
    from ...storage.amendments import list_amendments

    with get_connection() as conn:
        amendments = list_amendments(conn, task_id=task_id, status=status)

    return amendments


@router.get(
    "/projects/{project_id}/amendments/{amendment_id}",
    response_model=dict[str, Any],
)
async def get_amendment_endpoint(
    project_id: str,
    amendment_id: str,
) -> dict[str, Any]:
    """Get a specific amendment by ID.

    Args:
        project_id: Project ID (for validation)
        amendment_id: Amendment ID (e.g., amend-0001)

    Returns:
        Full amendment details.
    """
    from ...storage.amendments import get_amendment

    with get_connection() as conn:
        amendment = get_amendment(conn, amendment_id)

    if not amendment:
        raise HTTPException(
            status_code=404,
            detail=f"Amendment {amendment_id} not found",
        )

    return amendment


@router.patch(
    "/projects/{project_id}/amendments/{amendment_id}/approve",
    response_model=dict[str, Any],
)
async def approve_amendment_endpoint(
    project_id: str,
    amendment_id: str,
    request: AmendmentApproveRequest,
) -> dict[str, Any]:
    """Approve a pending amendment.

    On approval:
    1. Update amendment status to 'approved'
    2. Update criterion's verify_command with new command
    3. Reset preflight status to 'pending'

    Args:
        project_id: Project ID (for validation)
        amendment_id: Amendment ID to approve
        request: Approval details

    Returns:
        Approved amendment info.
    """
    from ...storage.amendments import approve_amendment

    with get_connection() as conn:
        result = approve_amendment(conn, amendment_id, request.approved_by, request.reason)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.patch(
    "/projects/{project_id}/amendments/{amendment_id}/reject",
    response_model=dict[str, Any],
)
async def reject_amendment_endpoint(
    project_id: str,
    amendment_id: str,
    request: AmendmentRejectRequest,
) -> dict[str, Any]:
    """Reject a pending amendment.

    The criterion's verify_command remains unchanged.

    Args:
        project_id: Project ID (for validation)
        amendment_id: Amendment ID to reject
        request: Rejection details with required reason

    Returns:
        Rejected amendment info.
    """
    from ...storage.amendments import reject_amendment

    with get_connection() as conn:
        result = reject_amendment(conn, amendment_id, request.rejected_by, request.reason)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result
