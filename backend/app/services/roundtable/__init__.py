"""Roundtable service package for multi-agent collaboration.

This package provides the roundtable functionality for multi-agent conversations
between Claude and Gemini, with codebase access via tools.

Main components:
- RoundtableService: Main service for managing roundtable sessions
- RoundtableSession: Session state and message management
- RoundtableMessage: Individual messages in a session
- Tools: Read-only and write access to the codebase
- Permissions: User permission management for write tools
- Extraction: TDD spec extraction from conversations
"""

# Import from executor module
from .executor import (
    MAX_FILE_SIZE,
    MAX_SEARCH_RESULTS,
    READ_TOOL_NAMES,
    WRITE_TOOL_NAMES,
    RoundtableToolExecutor,
    ToolResult,
    create_tool_function,
    format_tool_results_for_prompt,
    get_default_executor,
    get_tool_description,
    to_adk_function_tools,
    to_claude_sdk_tools,
)
from .extraction import (
    SPEC_EXTRACTION_PROMPT,
    accept_spec,
    extract_spec_from_conversation,
    get_effective_prompt,
)
from .permissions import (
    PendingPermission,
    PermissionManager,
    permission_manager,
)
from .service import (
    PermissionCallback,
    RoundtableService,
    TargetAgent,
    current_session_id,
    default_permission_callback,
    get_roundtable_service,
)
from .session import (
    RoundtableMessage,
    RoundtableSession,
)

# Import from tools package
from .tools import (
    ALL_CATEGORIES,
    READ_ONLY_TOOLS,
    WRITE_TOOLS,
    ToolCategory,
)
from .validation import get_allowed_bases

__all__ = [
    "ALL_CATEGORIES",
    "MAX_FILE_SIZE",
    "MAX_SEARCH_RESULTS",
    "READ_ONLY_TOOLS",
    "READ_TOOL_NAMES",
    "SPEC_EXTRACTION_PROMPT",
    "WRITE_TOOLS",
    "WRITE_TOOL_NAMES",
    "PendingPermission",
    "PermissionCallback",
    "PermissionManager",
    "RoundtableMessage",
    "RoundtableService",
    "RoundtableSession",
    "RoundtableToolExecutor",
    "TargetAgent",
    "ToolCategory",
    "ToolResult",
    "accept_spec",
    "create_tool_function",
    "current_session_id",
    "default_permission_callback",
    "extract_spec_from_conversation",
    "format_tool_results_for_prompt",
    "get_allowed_bases",
    "get_default_executor",
    "get_effective_prompt",
    "get_roundtable_service",
    "get_tool_description",
    "permission_manager",
    "to_adk_function_tools",
    "to_claude_sdk_tools",
]
