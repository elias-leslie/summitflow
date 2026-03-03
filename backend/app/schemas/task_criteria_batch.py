"""Acceptance criteria batch operation schemas."""

from backend.app.schemas.task_criteria_request import CreateTaskCriterionRequest
from pydantic import BaseModel


class BatchTaskCriterionCreate(CreateTaskCriterionRequest):
    """A single criterion to create in batch for a task."""

    task_id: int


class BatchTaskCriteriaRequest(BaseModel):
    """Request model for batch task criteria creation."""

    items: list[BatchTaskCriterionCreate]


class BatchCriterionResult(BaseModel):
    """Result for a single criterion in batch create."""

    criterion: str  # First 50 chars for identification
    success: bool
    id: int | None = None
    criterion_id: str | None = None
    error: str | None = None


class BatchTaskCriteriaResponse(BaseModel):
    """Response model for batch task criteria creation."""

    created: list[dict[str, object]]
    errors: list[BatchCriterionResult]
