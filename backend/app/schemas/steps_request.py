"""Request/input Pydantic models for step operations.

Covers create, update, insert, and batch-create request bodies.
"""

from typing import Any

from pydantic import BaseModel, Field


class StepInput(BaseModel):
    """Input model for a step - can be simple string or object with spec."""

    description: str = Field(min_length=5, description="Step description")
    spec: dict[str, Any] | None = Field(default=None, description="Step implementation spec")


class StepCreate(BaseModel):
    """Request model for creating a single step."""

    step_number: int = Field(ge=1, description="1-indexed step number")
    description: str = Field(min_length=5, description="Step description")
    spec: dict[str, Any] | None = Field(default=None, description="Step implementation spec")


class StepUpdate(BaseModel):
    """Request model for updating step pass status."""

    passes: bool = Field(description="Whether step passes/is complete")


class StepInsert(BaseModel):
    """Request model for inserting a step at a specific position."""

    description: str = Field(min_length=1, description="Step description")
    spec: dict[str, Any] | None = Field(default=None, description="Step implementation spec")


class StepCreateWithVerification(BaseModel):
    """Request model for creating a single step."""

    description: str = Field(min_length=1, description="Step description")
    spec: dict[str, Any] | None = Field(default=None, description="Step implementation spec")


class StepFieldsUpdate(BaseModel):
    """Request model for updating step fields (description only)."""

    description: str | None = Field(default=None, min_length=1, description="Step description")


class BatchStepCreate(BaseModel):
    """Request model for batch step creation.

    Steps can be provided as:
    - List of strings (description only, backward compatible)
    - List of StepInput objects with {description, spec}
    """

    steps: list[str | StepInput] = Field(
        min_length=1, description="List of steps (strings or {description, spec} objects)"
    )
