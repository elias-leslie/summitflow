"""Roundtable session and message models.

Contains the data structures for managing multi-agent roundtable conversations.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from ...constants import DEFAULT_CLAUDE_MODEL, DEFAULT_GEMINI_MODEL
from ..agents import AgentType

if TYPE_CHECKING:
    from .executor import RoundtableToolExecutor


@dataclass
class RoundtableMessage:
    """Message in a Roundtable session."""

    id: str
    agent: AgentType | Literal["user"]
    content: str
    timestamp: datetime
    tokens_used: int = 0
    model: str | None = None

    @classmethod
    def create(
        cls,
        agent: AgentType | Literal["user"],
        content: str,
        tokens_used: int = 0,
        model: str | None = None,
    ) -> RoundtableMessage:
        """Create a new message with auto-generated ID and timestamp."""
        return cls(
            id=str(uuid.uuid4()),
            agent=agent,
            content=content,
            timestamp=datetime.utcnow(),
            tokens_used=tokens_used,
            model=model,
        )


def _get_default_executor() -> RoundtableToolExecutor:
    """Lazy import to avoid circular dependency."""
    from .executor import get_default_executor

    return get_default_executor()


@dataclass
class RoundtableSession:
    """Active roundtable session with conversation history.

    Agents have read-only codebase access via tools by default.
    Additional tool permissions can be granted per session.
    """

    id: str
    project_id: str
    messages: list[RoundtableMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    mode: Literal["spec_driven", "quick"] = "quick"
    tool_executor: RoundtableToolExecutor = field(default_factory=_get_default_executor)
    tools_enabled: bool = True  # Enable by default
    agent_override: str | None = None  # Override agent type (claude/gemini)
    model_override: str | None = None  # Override model ID
    # SDK session IDs for resuming sessions with context
    claude_sdk_session_id: str | None = None
    gemini_sdk_session_id: str | None = None

    @classmethod
    def create(
        cls,
        project_id: str,
        mode: Literal["spec_driven", "quick"] = "quick",
        tools_enabled: bool = True,
        agent_override: str | None = None,
        model_override: str | None = None,
    ) -> RoundtableSession:
        """Create a new session with auto-generated ID."""
        return cls(
            id=str(uuid.uuid4()),
            project_id=project_id,
            mode=mode,
            tools_enabled=tools_enabled,
            agent_override=agent_override,
            model_override=model_override,
        )

    def add_message(self, message: RoundtableMessage) -> None:
        """Add a message to the session."""
        self.messages.append(message)

    def get_effective_agent(self, default_agent: AgentType = "claude") -> AgentType:
        """Get the effective agent type for this session.

        Uses session agent_override if set, otherwise falls back to default.

        Args:
            default_agent: Default agent type to use if no override

        Returns:
            Effective agent type
        """
        if self.agent_override and self.agent_override in ("claude", "gemini"):
            return self.agent_override  # type: ignore
        return default_agent

    def get_effective_model(
        self,
        agent_type: AgentType,
        default_claude: str = DEFAULT_CLAUDE_MODEL,
        default_gemini: str = DEFAULT_GEMINI_MODEL,
    ) -> str:
        """Get the effective model for this session.

        Uses session model_override if set, otherwise falls back to default.

        Args:
            agent_type: The agent type to get model for
            default_claude: Default Claude model
            default_gemini: Default Gemini model

        Returns:
            Effective model identifier
        """
        if self.model_override:
            return self.model_override
        return default_claude if agent_type == "claude" else default_gemini

    def get_context(self, max_messages: int = 20) -> str:
        """Build context string from recent messages for agent prompts."""
        recent = self.messages[-max_messages:]
        parts = []
        for msg in recent:
            speaker = msg.agent.upper() if msg.agent != "user" else "USER"
            parts.append(f"[{speaker}]: {msg.content}")
        return "\n\n".join(parts)
