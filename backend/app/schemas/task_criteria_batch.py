"""Acceptance criteria batch operation schemas."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class BatchTaskCriterionCreate(BaseModel):
    """A single criterion to create in batch for a task."""

    criterion: str = Field(min_length=10, description="Criterion text")
    category: Literal["performance", "correctness", "security", "quality"] = "correctness"
    measurement: str = "test"
    threshold: str | None = None
    verify_by: Literal["test", "opus", "human", "agent"] = "test"


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

    created: list[dict[str, Any]]
    errors: list[BatchCriterionResult]
