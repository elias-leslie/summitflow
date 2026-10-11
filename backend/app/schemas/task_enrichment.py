"""Task cleanup-prompt, capability and blocker schemas."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .task_criteria import AcceptanceCriterion


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
