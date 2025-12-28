"""History parser for mining Claude session JSONL files.

Parses ~/.claude/projects/{project}/*.jsonl files to extract:
- User messages and corrections
- Assistant responses
- Tool calls and outcomes
- Failed commands and recoveries
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    """Represents a tool call extracted from session history."""

    tool_name: str
    tool_input: dict[str, Any]
    tool_output: str | None = None
    success: bool = True
    error_message: str | None = None
    timestamp: str | None = None


@dataclass
class SessionMessage:
    """Represents a message in a session."""

    role: str  # "user" or "assistant"
    content: str
    timestamp: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    is_correction: bool = False  # User correcting previous behavior


@dataclass
class ParsedSession:
    """Parsed session with extracted data."""

    session_id: str
    project_path: str
    messages: list[SessionMessage] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    failed_commands: list[ToolCall] = field(default_factory=list)
    user_corrections: list[SessionMessage] = field(default_factory=list)
    timestamp_start: str | None = None
    timestamp_end: str | None = None


class HistoryParser:
    """Parse Claude session JSONL files for pattern extraction.

    Usage:
        parser = HistoryParser()
        sessions = parser.list_sessions("summitflow")
        for session in parser.parse_sessions(sessions[:10]):
            print(session.session_id, len(session.tool_calls))
    """

    # Standard Claude projects directory
    CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

    # Indicators of user corrections
    CORRECTION_INDICATORS: ClassVar[list[str]] = [
        "no,",
        "no ",
        "don't",
        "instead",
        "actually",
        "wrong",
        "not that",
        "stop",
        "cancel",
        "use this instead",
        "should be",
    ]

    # Indicators of failed commands (in tool output)
    FAILURE_INDICATORS: ClassVar[list[str]] = [
        "error:",
        "Error:",
        "ERROR:",
        "failed",
        "Failed",
        "FAILED",
        "exception",
        "Exception",
        "traceback",
        "Traceback",
        "command not found",
        "No such file",
        "Permission denied",
        "fatal:",
        "Fatal:",
    ]

    def __init__(self, projects_dir: Path | None = None):
        """Initialize parser.

        Args:
            projects_dir: Override Claude projects directory (for testing)
        """
        self.projects_dir = projects_dir or self.CLAUDE_PROJECTS_DIR

    def _get_project_dir(self, project_name: str) -> Path:
        """Get the project directory path for a given project name.

        Claude uses path encoding like: -home-kasadis-summitflow
        """
        # Try exact match first
        for path in self.projects_dir.iterdir():
            if path.is_dir() and project_name in path.name:
                return path

        # Fallback: construct the path directly
        return self.projects_dir / f"-home-kasadis-{project_name}"

    def list_sessions(
        self,
        project_name: str,
        limit: int | None = None,
        since: datetime | None = None,
    ) -> list[Path]:
        """List session files for a project.

        Args:
            project_name: Project name (e.g., "summitflow")
            limit: Maximum sessions to return (most recent first)
            since: Only return sessions modified after this time

        Returns:
            List of session file paths, sorted by modification time (newest first)
        """
        project_dir = self._get_project_dir(project_name)

        if not project_dir.exists():
            logger.warning(f"Project directory not found: {project_dir}")
            return []

        sessions = []
        for path in project_dir.glob("*.jsonl"):
            if since:
                mtime = datetime.fromtimestamp(path.stat().st_mtime)
                if mtime < since:
                    continue
            sessions.append(path)

        # Sort by modification time, newest first
        sessions.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        if limit:
            sessions = sessions[:limit]

        return sessions

    def parse_session_file(self, path: Path) -> ParsedSession:
        """Parse a single session JSONL file.

        Args:
            path: Path to session JSONL file

        Returns:
            ParsedSession with extracted data
        """
        session_id = path.stem
        project_path = str(path.parent)

        session = ParsedSession(
            session_id=session_id,
            project_path=project_path,
        )

        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            logger.error(f"Failed to read session file {path}: {e}")
            return session

        pending_tool_calls: dict[str, ToolCall] = {}  # tool_use_id -> ToolCall

        for line in lines:
            try:
                entry = json.loads(line.strip())
            except json.JSONDecodeError:
                continue

            entry_type = entry.get("type")
            timestamp = entry.get("timestamp")

            # Track session time range
            if timestamp:
                if not session.timestamp_start:
                    session.timestamp_start = timestamp
                session.timestamp_end = timestamp

            if entry_type == "user":
                self._process_user_entry(entry, session, pending_tool_calls)
            elif entry_type == "assistant":
                self._process_assistant_entry(entry, session, pending_tool_calls)

        return session

    def _process_user_entry(
        self,
        entry: dict[str, Any],
        session: ParsedSession,
        pending_tool_calls: dict[str, ToolCall],
    ) -> None:
        """Process a user-type entry."""
        message = entry.get("message", {})
        content = message.get("content")
        timestamp = entry.get("timestamp")

        # Handle tool results (content is a list with tool_result items)
        if isinstance(content, list):
            for item in content:
                if item.get("type") == "tool_result":
                    tool_use_id = item.get("tool_use_id")
                    result_content = item.get("content", "")

                    # Link result to pending tool call
                    if tool_use_id in pending_tool_calls:
                        tool_call = pending_tool_calls.pop(tool_use_id)
                        tool_call.tool_output = result_content
                        tool_call.timestamp = timestamp

                        # Check for failure indicators
                        if self._is_failure_output(result_content):
                            tool_call.success = False
                            tool_call.error_message = self._extract_error(result_content)
                            session.failed_commands.append(tool_call)

                        session.tool_calls.append(tool_call)
            return

        # Handle regular user messages
        if isinstance(content, str):
            is_correction = self._is_correction(content)
            msg = SessionMessage(
                role="user",
                content=content,
                timestamp=timestamp,
                is_correction=is_correction,
            )
            session.messages.append(msg)

            if is_correction:
                session.user_corrections.append(msg)

    def _process_assistant_entry(
        self,
        entry: dict[str, Any],
        session: ParsedSession,
        pending_tool_calls: dict[str, ToolCall],
    ) -> None:
        """Process an assistant-type entry."""
        message = entry.get("message", {})
        content_items = message.get("content", [])
        timestamp = entry.get("timestamp")

        text_parts = []
        for item in content_items:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                elif item.get("type") == "tool_use":
                    tool_call = ToolCall(
                        tool_name=item.get("name", "unknown"),
                        tool_input=item.get("input", {}),
                        timestamp=timestamp,
                    )
                    # Track pending tool call for result linking
                    tool_id = item.get("id")
                    if tool_id:
                        pending_tool_calls[tool_id] = tool_call

        if text_parts:
            msg = SessionMessage(
                role="assistant",
                content="\n".join(text_parts),
                timestamp=timestamp,
            )
            session.messages.append(msg)

    def _is_correction(self, content: str) -> bool:
        """Check if user message appears to be a correction."""
        content_lower = content.lower().strip()
        return any(indicator in content_lower for indicator in self.CORRECTION_INDICATORS)

    def _is_failure_output(self, output: str) -> bool:
        """Check if tool output indicates a failure."""
        if not output:
            return False
        return any(indicator in output for indicator in self.FAILURE_INDICATORS)

    def _extract_error(self, output: str) -> str | None:
        """Extract error message from failure output."""
        # Return first line containing an error indicator
        for line in output.split("\n"):
            if any(ind in line for ind in self.FAILURE_INDICATORS):
                return line.strip()[:200]
        return None

    def parse_sessions(
        self,
        session_paths: list[Path],
        *,
        yield_progress: bool = False,
    ):
        """Parse multiple session files.

        Args:
            session_paths: List of session file paths
            yield_progress: If True, yield (index, total, session) tuples

        Yields:
            ParsedSession objects (or tuples if yield_progress=True)
        """
        total = len(session_paths)
        for idx, path in enumerate(session_paths):
            try:
                session = self.parse_session_file(path)
                if yield_progress:
                    yield (idx, total, session)
                else:
                    yield session
            except Exception as e:
                logger.error(f"Failed to parse session {path}: {e}")
                continue

    def get_session_stats(self, project_name: str) -> dict[str, Any]:
        """Get statistics about sessions for a project.

        Returns:
            Dict with session count, total size, date range, etc.
        """
        project_dir = self._get_project_dir(project_name)

        if not project_dir.exists():
            return {"exists": False, "project_dir": str(project_dir)}

        sessions = list(project_dir.glob("*.jsonl"))
        if not sessions:
            return {
                "exists": True,
                "project_dir": str(project_dir),
                "session_count": 0,
                "total_size_bytes": 0,
            }

        total_size = sum(p.stat().st_size for p in sessions)
        mtimes = [p.stat().st_mtime for p in sessions]

        return {
            "exists": True,
            "project_dir": str(project_dir),
            "session_count": len(sessions),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 1),
            "oldest_session": datetime.fromtimestamp(min(mtimes)).isoformat() if mtimes else None,
            "newest_session": datetime.fromtimestamp(max(mtimes)).isoformat() if mtimes else None,
        }
