"""Workflow API models.

Request and response models for workflow endpoints.
"""

from pydantic import BaseModel


class PlanApproveRequest(BaseModel):
    """Request body for plan approval."""

    approved_by: str = "user"
    notes: str | None = None


class PlanApproveResponse(BaseModel):
    """Response for plan approval."""

    task_id: str
    plan_status: str
    plan_approved_at: str | None
    plan_approved_by: str | None
    message: str
