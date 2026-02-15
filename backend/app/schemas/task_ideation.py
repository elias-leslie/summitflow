"""Ideation agent task creation schema.

Accepts the structured output from the ideation agent's create_task tool
and maps it to SummitFlow's task model with automatic Hatchet dispatch.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


# Complexity values as the ideation agent sends them (lowercase)
IdeationComplexity = Literal["simple", "standard", "complex"]

# Mapping from ideation agent complexity to DB enum
_COMPLEXITY_MAP: dict[str, str] = {
    "simple": "SIMPLE",
    "standard": "STANDARD",
    "complex": "COMPLEX",
}


class IdeationTaskCreate(BaseModel):
    """Request model for creating a task from ideation agent output.

    Accepts the exact schema the ideation agent produces and maps
    it cleanly to SummitFlow's task model.
    """

    title: str = Field(description="Task title from ideation agent")
    description: str = Field(description="Detailed task description")
    priority: int = Field(
        default=2, ge=0, le=4, description="Priority P0-P4 (0=critical, 4=backlog)"
    )
    task_type: Literal["feature", "bug", "task", "refactor", "debt", "regression"] = Field(
        default="task", description="Task type classification"
    )
    labels: list[str] = Field(
        default_factory=list, description="Labels (e.g. ['domains:backend', 'scope:api'])"
    )
    complexity: IdeationComplexity | None = Field(
        default=None, description="Task complexity: simple, standard, or complex"
    )
    auto_dispatch: bool = Field(
        default=False,
        description="Automatically dispatch to Hatchet pipeline after creation",
    )

    @field_validator("complexity", mode="before")
    @classmethod
    def normalize_complexity(cls, v: str | None) -> str | None:
        """Accept both lowercase and uppercase complexity values."""
        if v is None:
            return v
        return v.lower()

    def to_db_complexity(self) -> str | None:
        """Convert ideation complexity to DB enum (uppercase)."""
        if self.complexity is None:
            return None
        return _COMPLEXITY_MAP[self.complexity]


class IdeationTaskResponse(BaseModel):
    """Response model for ideation task creation."""

    task_id: str
    project_id: str
    status: str
    dispatched: bool = Field(description="Whether the task was dispatched to Hatchet")
    dispatch_stage: str | None = Field(
        default=None, description="Pipeline stage dispatched to (triage/planning/execution)"
    )
