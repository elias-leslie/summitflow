"""Acceptance criteria validation schemas."""

from pydantic import BaseModel, Field

from .task_criteria_core import AcceptanceCriterion


class CriteriaValidateRequest(BaseModel):
    """Request model for validating acceptance criteria."""

    objective: str = Field(min_length=10, description="Task objective for context")
    criteria: list[AcceptanceCriterion] = Field(description="Criteria to validate")


class CriterionFailure(BaseModel):
    """Single criterion validation failure."""

    criterion_id: str
    valid: bool
    issues: list[str] = Field(default_factory=list)
    suggestion: str | None = None


class CriteriaValidateResponse(BaseModel):
    """Response model for criteria validation."""

    valid: bool
    failures: list[CriterionFailure] = Field(default_factory=list)
