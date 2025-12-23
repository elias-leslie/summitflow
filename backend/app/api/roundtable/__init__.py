"""Roundtable API package for multi-agent collaboration.

Provides REST endpoints for creating sessions, sending messages,
and generating features from conversations.
"""

from fastapi import APIRouter

from . import messages, prompts, sessions, specs
from .models import (
    AcceptSpecRequest,
    AcceptSpecResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    EndSessionRequest,
    EndSessionResponse,
    ExtractionPromptConfig,
    ExtractionPromptsExport,
    GenerateSpecRequest,
    GenerateSpecResponse,
    GetSpecResponse,
    MessageRequest,
    MessageResponse,
    PermissionResolution,
    PermissionResolutionResponse,
    SendMessageResponse,
    SessionAgentConfig,
    SessionInfo,
    ToolStats,
    UpdateExtractionPromptRequest,
    UpdateSessionAgentRequest,
    UpdateSessionRequest,
    UpdateSessionResponse,
    UpdateToolsRequest,
    UpdateToolsResponse,
)

# Create the main router that aggregates all sub-routers
router = APIRouter()

# Include all sub-routers (no prefix - paths are defined in each router)
router.include_router(sessions.router, tags=["roundtable"])
router.include_router(messages.router, tags=["roundtable"])
router.include_router(prompts.router, tags=["roundtable"])
router.include_router(specs.router, tags=["roundtable"])

__all__ = [
    # Models
    "AcceptSpecRequest",
    "AcceptSpecResponse",
    "CreateSessionRequest",
    "CreateSessionResponse",
    "EndSessionRequest",
    "EndSessionResponse",
    "ExtractionPromptConfig",
    "ExtractionPromptsExport",
    "GenerateSpecRequest",
    "GenerateSpecResponse",
    "GetSpecResponse",
    "MessageRequest",
    "MessageResponse",
    "PermissionResolution",
    "PermissionResolutionResponse",
    "SendMessageResponse",
    "SessionAgentConfig",
    "SessionInfo",
    "ToolStats",
    "UpdateExtractionPromptRequest",
    "UpdateSessionAgentRequest",
    "UpdateSessionRequest",
    "UpdateSessionResponse",
    "UpdateToolsRequest",
    "UpdateToolsResponse",
    "router",
]
