"""Roundtable service for multi-agent collaboration.

Routes messages between user and multiple AI agents (Claude, Gemini).
Supports targeting specific agents or broadcasting to both.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from .agents import AgentType, LLMResponse, get_agent

logger = logging.getLogger(__name__)

TargetAgent = Literal["claude", "gemini", "both"]


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


@dataclass
class RoundtableSession:
    """Active roundtable session with conversation history."""

    id: str
    project_id: str
    messages: list[RoundtableMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    mode: Literal["spec_driven", "quick"] = "quick"

    @classmethod
    def create(
        cls,
        project_id: str,
        mode: Literal["spec_driven", "quick"] = "quick",
    ) -> RoundtableSession:
        """Create a new session with auto-generated ID."""
        return cls(
            id=str(uuid.uuid4()),
            project_id=project_id,
            mode=mode,
        )

    def add_message(self, message: RoundtableMessage) -> None:
        """Add a message to the session."""
        self.messages.append(message)

    def get_context(self, max_messages: int = 20) -> str:
        """Build context string from recent messages for agent prompts."""
        recent = self.messages[-max_messages:]
        parts = []
        for msg in recent:
            speaker = msg.agent.upper() if msg.agent != "user" else "USER"
            parts.append(f"[{speaker}]: {msg.content}")
        return "\n\n".join(parts)


class RoundtableService:
    """Service for multi-agent roundtable conversations.

    Supports:
    - Routing messages to specific agents
    - Broadcasting to both agents
    - Maintaining conversation context
    - Turn-taking between agents
    """

    # System prompt for roundtable context
    ROUNDTABLE_SYSTEM = """You are participating in a collaborative roundtable discussion.
Other participants include the user and potentially another AI assistant.
Previous messages in the conversation are provided for context.

Guidelines:
1. Be collaborative and build on others' ideas
2. If you disagree, explain your reasoning
3. Be concise but thorough
4. Focus on helping the user achieve their goals
5. If the other AI has already addressed a point well, acknowledge it rather than repeating
"""

    def __init__(
        self,
        claude_model: str = "sonnet",
        gemini_model: str = "gemini-2.5-flash",
    ) -> None:
        """Initialize roundtable service with model configurations."""
        self.claude_model = claude_model
        self.gemini_model = gemini_model
        self._sessions: dict[str, RoundtableSession] = {}

    def get_session(self, session_id: str) -> RoundtableSession | None:
        """Get an existing session by ID."""
        return self._sessions.get(session_id)

    def create_session(
        self,
        project_id: str,
        mode: Literal["spec_driven", "quick"] = "quick",
    ) -> RoundtableSession:
        """Create a new roundtable session."""
        session = RoundtableSession.create(project_id, mode)
        self._sessions[session.id] = session
        return session

    def route_message(
        self,
        session: RoundtableSession,
        message: str,
        target: TargetAgent = "both",
    ) -> list[RoundtableMessage]:
        """Route a message to target agent(s) and get responses.

        Args:
            session: The roundtable session
            message: User's message
            target: Target agent ("claude", "gemini", or "both")

        Returns:
            List of response messages from agent(s)
        """
        # Add user message to session
        user_msg = RoundtableMessage.create("user", message)
        session.add_message(user_msg)

        responses: list[RoundtableMessage] = []

        # Build context from conversation history
        context = session.get_context()

        if target in ("claude", "both"):
            try:
                response = self._send_to_agent("claude", message, context)
                msg = RoundtableMessage.create(
                    "claude",
                    response.content,
                    tokens_used=response.usage.get("total_tokens", 0),
                    model=response.model,
                )
                session.add_message(msg)
                responses.append(msg)
            except Exception as e:
                logger.error(f"Claude error: {e}")
                error_msg = RoundtableMessage.create(
                    "claude", f"[Error: {e!s}]"
                )
                session.add_message(error_msg)
                responses.append(error_msg)

        if target in ("gemini", "both"):
            # If both agents, update context with Claude's response
            if target == "both" and responses:
                context = session.get_context()

            try:
                response = self._send_to_agent("gemini", message, context)
                msg = RoundtableMessage.create(
                    "gemini",
                    response.content,
                    tokens_used=response.usage.get("total_tokens", 0),
                    model=response.model,
                )
                session.add_message(msg)
                responses.append(msg)
            except Exception as e:
                logger.error(f"Gemini error: {e}")
                error_msg = RoundtableMessage.create(
                    "gemini", f"[Error: {e!s}]"
                )
                session.add_message(error_msg)
                responses.append(error_msg)

        return responses

    async def route_message_async(
        self,
        session: RoundtableSession,
        message: str,
        target: TargetAgent = "both",
    ) -> AsyncGenerator[RoundtableMessage, None]:
        """Route a message asynchronously, yielding responses as they arrive.

        Args:
            session: The roundtable session
            message: User's message
            target: Target agent ("claude", "gemini", or "both")

        Yields:
            Response messages from agent(s) as they complete
        """
        # Add user message to session
        user_msg = RoundtableMessage.create("user", message)
        session.add_message(user_msg)

        # Build context from conversation history
        context = session.get_context()

        if target in ("claude", "both"):
            try:
                # Run in thread pool to avoid blocking
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self._send_to_agent,
                    "claude",
                    message,
                    context,
                )
                msg = RoundtableMessage.create(
                    "claude",
                    response.content,
                    tokens_used=response.usage.get("total_tokens", 0),
                    model=response.model,
                )
                session.add_message(msg)
                yield msg

                # Update context with Claude's response for Gemini
                context = session.get_context()
            except Exception as e:
                logger.error(f"Claude error: {e}")
                error_msg = RoundtableMessage.create(
                    "claude", f"[Error: {e!s}]"
                )
                session.add_message(error_msg)
                yield error_msg

        if target in ("gemini", "both"):
            try:
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self._send_to_agent,
                    "gemini",
                    message,
                    context,
                )
                msg = RoundtableMessage.create(
                    "gemini",
                    response.content,
                    tokens_used=response.usage.get("total_tokens", 0),
                    model=response.model,
                )
                session.add_message(msg)
                yield msg
            except Exception as e:
                logger.error(f"Gemini error: {e}")
                error_msg = RoundtableMessage.create(
                    "gemini", f"[Error: {e!s}]"
                )
                session.add_message(error_msg)
                yield error_msg

    def _send_to_agent(
        self,
        agent_type: AgentType,
        message: str,
        context: str,
    ) -> LLMResponse:
        """Send message to a specific agent with context."""
        model = (
            self.claude_model if agent_type == "claude" else self.gemini_model
        )
        agent = get_agent(agent_type, model=model)

        # Build prompt with context
        prompt = message
        if context:
            prompt = f"""Previous conversation:
{context}

New message from user:
{message}

Respond to the user's latest message, taking into account the full conversation context."""

        return agent.generate(
            prompt=prompt,
            system=self.ROUNDTABLE_SYSTEM,
            max_tokens=4096,
            temperature=0.7,
        )

    async def get_parallel_responses(
        self,
        session: RoundtableSession,
        message: str,
    ) -> list[RoundtableMessage]:
        """Get responses from both agents in parallel.

        Faster than sequential routing when both agents are needed.
        """
        # Add user message to session
        user_msg = RoundtableMessage.create("user", message)
        session.add_message(user_msg)

        context = session.get_context()
        loop = asyncio.get_event_loop()

        # Run both agents in parallel
        claude_task = loop.run_in_executor(
            None, self._send_to_agent, "claude", message, context
        )
        gemini_task = loop.run_in_executor(
            None, self._send_to_agent, "gemini", message, context
        )

        results = await asyncio.gather(claude_task, gemini_task, return_exceptions=True)
        responses: list[RoundtableMessage] = []

        for agent_type, result in zip(["claude", "gemini"], results, strict=True):
            if isinstance(result, Exception):
                msg = RoundtableMessage.create(
                    agent_type,  # type: ignore
                    f"[Error: {result!s}]",
                )
            else:
                msg = RoundtableMessage.create(
                    agent_type,  # type: ignore
                    result.content,
                    tokens_used=result.usage.get("total_tokens", 0),
                    model=result.model,
                )
            session.add_message(msg)
            responses.append(msg)

        return responses


# Module-level singleton for convenience
_roundtable_service: RoundtableService | None = None


def get_roundtable_service() -> RoundtableService:
    """Get or create the roundtable service singleton."""
    global _roundtable_service
    if _roundtable_service is None:
        _roundtable_service = RoundtableService()
    return _roundtable_service
