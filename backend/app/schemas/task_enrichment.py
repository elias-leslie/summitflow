"""Task AI enrichment schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from ..constants import TaskType

if TYPE_CHECKING:
    from .task_base import TaskResponse
    from .task_criteria import AcceptanceCriterion


class EnrichmentRequest(BaseModel):
    """Request model for triggering AI task enrichment."""

    raw_request: str = Field(min_length=10, description="Natural language task description")
    priority: int | None = Field(default=None, ge=0, le=4, description="Optional priority override")
    task_type: TaskType | None = Field(
        default=None, description="Optional type override"
    )


class EnrichmentResponse(BaseModel):
    """Response model after starting enrichment."""

    task_id: str
    enrichment_status: str
    message: str


class DiscussionMessage(BaseModel):
    """A single message in a task discussion."""

    role: Literal["user", "assistant"]
    content: str
    timestamp: str


class DiscussionRequest(BaseModel):
    """Request model for discussing a task with AI."""

    message: str = Field(min_length=1, description="User message")


class DiscussionResponse(BaseModel):
    """Response model for task discussion."""

    response: str = Field(description="Agent response text")
    updated_task: TaskResponse | None = Field(
        default=None, description="Updated task if changes were made"
    )
    history: list[DiscussionMessage] = Field(
        default_factory=list, description="Full conversation history"
    )


class CleanupPromptRequest(BaseModel):
    """Request model for AI prompt cleanup."""

    raw_request: str = Field(min_length=5, description="Raw user input to clean up")


class CleanupPromptResponse(BaseModel):
    """Response model for prompt cleanup."""

    cleaned_prompt: str
    changes_made: list[str] = Field(default_factory=list)


class CapabilityContext(BaseModel):
    """Capability context for a task."""

    id: int  # Database ID
    capability_id: str  # String ID like login, password-reset
    name: str
    criteria_passed: int
    criteria_total: int
    acceptance_criteria: list[AcceptanceCriterion] | None = None


class BlockerInfo(BaseModel):
    """Information about a blocking task."""

    id: str
    title: str
    status: str
    priority: int
