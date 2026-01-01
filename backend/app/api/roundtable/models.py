"""Pydantic models for roundtable API endpoints."""

from typing import Any

from pydantic import BaseModel

from ...constants import DEFAULT_CLAUDE_MODEL
from ...services.roundtable import TargetAgent

# ============================================================================
# Session Models
# ============================================================================


class CreateSessionRequest(BaseModel):
    """Request to create a new roundtable session."""

    title: str | None = None  # Optional session title
    mode: str = "quick"  # "spec_driven" or "quick"
    agent_mode: str = "both"  # "claude", "gemini", or "both"
    tools_enabled: bool = True  # Enable codebase read access by default
    write_enabled: bool = False  # Disable write access by default
    yolo_mode: bool = False  # Disable YOLO mode by default


class CreateSessionResponse(BaseModel):
    """Response after creating a session."""

    session_id: str
    project_id: str
    title: str | None = None
    mode: str
    agent_mode: str = "both"
    status: str = "active"
    tools_enabled: bool = True
    write_enabled: bool = False
    yolo_mode: bool = False


class ToolStats(BaseModel):
    """Tool usage statistics."""

    total_calls: int = 0
    files_read: int = 0
    searches: int = 0
    writes: int = 0


class UpdateToolsRequest(BaseModel):
    """Request to update tools settings."""

    tools_enabled: bool | None = None  # Enable/disable read tools
    write_enabled: bool | None = None  # Enable/disable write tools
    yolo_mode: bool | None = None  # Enable/disable YOLO mode (auto-approve all)


class UpdateToolsResponse(BaseModel):
    """Response after updating tools settings."""

    session_id: str
    tools_enabled: bool
    write_enabled: bool
    yolo_mode: bool
    tool_stats: ToolStats


class SessionInfo(BaseModel):
    """Session info for listing."""

    id: str
    project_id: str
    title: str | None = None
    status: str = "active"
    mode: str
    agent_mode: str = "both"
    tools_enabled: bool = True
    write_enabled: bool = False
    yolo_mode: bool = False
    tool_stats: ToolStats | None = None
    agent_override: str | None = None
    model_override: str | None = None
    message_count: int
    feature_count: int
    created_at: str
    updated_at: str


class UpdateSessionRequest(BaseModel):
    """Request to update a session's metadata."""

    title: str | None = None
    status: str | None = None  # "active" or "archived"
    agent_mode: str | None = None  # "claude", "gemini", or "both"


class UpdateSessionResponse(BaseModel):
    """Response after updating a session."""

    id: str
    project_id: str
    title: str | None = None
    status: str
    agent_mode: str
    updated_at: str


class SessionAgentConfig(BaseModel):
    """Agent configuration for a session."""

    agent_override: str | None = None
    model_override: str | None = None


class UpdateSessionAgentRequest(BaseModel):
    """Request to update session agent configuration."""

    agent_override: str | None = None
    model_override: str | None = None


class EndSessionRequest(BaseModel):
    """Request to end a session with optional checkpoint."""

    summary: str | None = None
    completed_steps: list[str] | None = None
    remaining_steps: list[str] | None = None
    create_checkpoint: bool = True


class EndSessionResponse(BaseModel):
    """Response after ending a session."""

    session_id: str
    status: str
    checkpoint_id: str | None = None
    checkpoint_created: bool = False


# ============================================================================
# Message Models
# ============================================================================


class MessageRequest(BaseModel):
    """Request to send a message in a session."""

    message: str
    target: TargetAgent = "both"  # "claude", "gemini", or "both"


class MessageResponse(BaseModel):
    """Single message in response."""

    id: str
    agent: str
    content: str
    timestamp: str
    tokens_used: int = 0
    model: str | None = None


class SendMessageResponse(BaseModel):
    """Response after sending a message."""

    user_message: MessageResponse
    responses: list[MessageResponse]


# ============================================================================
# Permission Models
# ============================================================================


class PermissionResolution(BaseModel):
    """Request to resolve a pending permission."""

    approved: bool


class PermissionResolutionResponse(BaseModel):
    """Response after resolving a permission."""

    status: str
    approved: bool


# ============================================================================
# Extraction Prompts Models
# ============================================================================


class ExtractionPromptConfig(BaseModel):
    """Configuration for an extraction prompt."""

    prompt_type: str
    prompt_text: str
    primary_agent: str = "claude"
    primary_model: str = DEFAULT_CLAUDE_MODEL
    is_default: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class UpdateExtractionPromptRequest(BaseModel):
    """Request to update an extraction prompt."""

    prompt_text: str
    primary_agent: str = "claude"
    primary_model: str = DEFAULT_CLAUDE_MODEL


class ExtractionPromptsExport(BaseModel):
    """Export format for extraction prompts."""

    project_id: str
    exported_at: str
    prompts: list[ExtractionPromptConfig]


# ============================================================================
# TDD Spec Models
# ============================================================================


class GenerateSpecRequest(BaseModel):
    """Request to generate a TDD spec from conversation."""

    agent_type: str = "gemini"  # Which agent to use for extraction


class GenerateSpecResponse(BaseModel):
    """Response from spec generation."""

    session_id: str
    spec: dict[str, Any]
    components_count: int
    capabilities_count: int
    tests_count: int


class AcceptSpecRequest(BaseModel):
    """Request to accept a generated spec."""

    accepted_by: str = "user"  # Who accepted (user or agent name)


class AcceptSpecResponse(BaseModel):
    """Response from spec acceptance."""

    spec_id: str
    components_created: int
    capabilities_created: int
    tests_created: int


class GetSpecResponse(BaseModel):
    """Response for getting a session's generated spec."""

    session_id: str
    spec: dict[str, Any] | None
