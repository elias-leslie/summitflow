"""Acceptance criteria CRUD request schemas."""

from typing import Literal

from pydantic import BaseModel, Field


class CreateTaskCriterionRequest(BaseModel):
    """Request model for creating a task-specific criterion."""

    criterion: str = Field(min_length=10, description="Criterion text")
    category: Literal["performance", "correctness", "security", "quality"] = "correctness"
    measurement: str = "test"
    threshold: str | None = None
    verify_by: Literal["test", "opus", "human", "agent"] = "test"


class VerifyTaskCriterionRequest(BaseModel):
    """Request model for verifying a task criterion."""

    verified: bool = True
    verified_by: Literal["opus", "test", "human", "agent"] = "human"


class UpdateTaskCriterionRequest(BaseModel):
    """Request model for updating a task criterion."""

    criterion: str | None = Field(default=None, min_length=10, description="Criterion text")
    category: Literal["performance", "correctness", "security", "quality"] | None = None
    verify_by: Literal["test", "opus", "human", "agent"] | None = None
