"""Task acceptance criteria schemas."""

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class AcceptanceCriterion(BaseModel):
    """Acceptance criterion for AI agent reliability.

    Each criterion must be specific, measurable, and verifiable.
    The id must match pattern ac-NNN (e.g., ac-001, ac-012).
    """

    id: str = Field(description="Unique ID in format ac-NNN")
    criterion: str = Field(min_length=10, description="Specific measurable condition")
    category: Literal["performance", "correctness", "security", "quality"] = Field(
        default="correctness", description="Category of the criterion"
    )
    measurement: str = Field(
        default="test", description="How to verify: test, metric, tool, manual"
    )
    threshold: str | None = Field(
        default=None, description="Specific value or condition (e.g., '<200ms', '100%')"
    )
    test_file: str | None = Field(default=None, description="Test file path when agent writes test")
    test_name: str | None = Field(
        default=None, description="Test function name when agent writes test"
    )
    verified: bool = Field(default=False, description="Whether criterion has been verified")
    verified_at: datetime | None = Field(default=None, description="When criterion was verified")
    verified_by: Literal["opus", "test", "human", "agent"] | None = Field(
        default=None, description="Who verified the criterion"
    )

    @field_validator("id")
    @classmethod
    def validate_id_format(cls, v: str) -> str:
        """Validate that id matches pattern ac-NNN."""
        if not re.match(r"^ac-\d{3}$", v):
            raise ValueError("id must match pattern ac-NNN (e.g., ac-001)")
        return v

    @field_validator("criterion")
    @classmethod
    def validate_criterion_not_vague(cls, v: str) -> str:
        """Basic validation that criterion is not too vague."""
        vague_patterns = ["is good", "works well", "is fast", "is efficient"]
        lower_v = v.lower()
        for pattern in vague_patterns:
            if pattern in lower_v and len(v) < 30:
                raise ValueError(f"Criterion too vague. Avoid patterns like '{pattern}'.")
        return v


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


class CreateTaskCriterionRequest(BaseModel):
    """Request model for creating a task-specific criterion."""

    criterion: str = Field(min_length=10, description="Criterion text")
    category: Literal["performance", "correctness", "security", "quality"] = "correctness"
    measurement: str = "test"
    threshold: str | None = None
    verify_command: str | None = Field(
        default=None, description="Bash command to verify this criterion"
    )
    verify_by: Literal["test", "opus", "human", "agent"] = "test"


class VerifyTaskCriterionRequest(BaseModel):
    """Request model for verifying a task criterion."""

    verified: bool = True
    verified_by: Literal["opus", "test", "human", "agent"] = "human"


class UpdateTaskCriterionRequest(BaseModel):
    """Request model for updating a task criterion."""

    criterion: str | None = Field(default=None, min_length=10, description="Criterion text")
    category: Literal["performance", "correctness", "security", "quality"] | None = None
    verify_command: str | None = Field(
        default=None, description="Bash command to verify this criterion"
    )
    verify_by: Literal["test", "opus", "human", "agent"] | None = None


class BatchTaskCriterionCreate(BaseModel):
    """A single criterion to create in batch for a task."""

    criterion: str = Field(min_length=10, description="Criterion text")
    category: Literal["performance", "correctness", "security", "quality"] = "correctness"
    measurement: str = "test"
    threshold: str | None = None
    verify_command: str | None = Field(
        default=None, description="Bash command to verify this criterion"
    )
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
