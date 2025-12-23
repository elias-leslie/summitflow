"""Helper functions for roundtable API endpoints."""

from datetime import datetime
from typing import Any

from ...services.roundtable import (
    RoundtableMessage,
    RoundtableService,
    RoundtableSession,
)
from ...storage import roundtable as roundtable_storage


def restore_session_from_db(
    service: RoundtableService,
    session_id: str,
    project_id: str,
) -> RoundtableSession | None:
    """Load a session from DB and restore it in memory with all state.

    Helper to avoid duplicating session restoration logic across endpoints.
    Restores messages, agent config, and SDK session IDs.

    Args:
        service: RoundtableService instance
        session_id: Session ID to load
        project_id: Project ID for validation

    Returns:
        Restored RoundtableSession or None if not found
    """
    db_session = roundtable_storage.load_session(session_id)
    if not db_session:
        return None

    # Create session in memory with agent config
    session = service.create_session(
        project_id,
        mode=db_session.get("mode", "quick"),
    )
    session.id = session_id
    session.agent_override = db_session.get("agent_override")
    session.model_override = db_session.get("model_override")

    # Restore SDK session IDs for context resume
    session.claude_sdk_session_id = db_session.get("claude_sdk_session_id")
    session.gemini_sdk_session_id = db_session.get("gemini_sdk_session_id")

    # Restore messages
    for msg_data in db_session.get("messages", []):
        msg = RoundtableMessage(
            id=msg_data.get("id", ""),
            agent=msg_data.get("agent", "user"),
            content=msg_data.get("content", ""),
            timestamp=datetime.fromisoformat(
                msg_data.get("timestamp", datetime.utcnow().isoformat())
            ),
            tokens_used=msg_data.get("tokens_used", 0),
            model=msg_data.get("model"),
        )
        session.messages.append(msg)

    service._sessions[session_id] = session
    return session


def get_preview(tool_name: str, tool_args: dict[str, Any]) -> str:
    """Generate a human-readable preview of a tool operation.

    Returns a truncated preview (max 500 chars) suitable for display
    in the permission dialog.

    Args:
        tool_name: Name of the tool being called
        tool_args: Arguments passed to the tool

    Returns:
        Human-readable preview string
    """
    if tool_name == "write_file":
        content = tool_args.get("content", "")
        path = tool_args.get("file_path", "unknown")
        preview = f"File: {path}\n\nContent:\n{content[:400]}"
        if len(content) > 400:
            preview += "..."
        return preview[:500]

    elif tool_name == "edit_file":
        old = tool_args.get("old_string", "")[:150]
        new = tool_args.get("new_string", "")[:150]
        path = tool_args.get("file_path", "unknown")
        preview = f"File: {path}\n\nReplace:\n{old}\n\nWith:\n{new}"
        return preview[:500]

    elif tool_name == "delete_file":
        path = tool_args.get("file_path", "unknown")
        return f"Delete file: {path}"

    elif tool_name == "create_directory":
        path = tool_args.get("path", "unknown")
        return f"Create directory: {path}"

    # Generic fallback
    preview = str(tool_args)
    if len(preview) > 500:
        preview = preview[:497] + "..."
    return preview
