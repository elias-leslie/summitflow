"""Roundtable service for multi-agent collaboration.

Routes messages between user and multiple AI agents (Claude, Gemini).
Supports targeting specific agents or broadcasting to both.
Agents have read-only access to the codebase via tools.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from .agents import AgentType, LLMResponse, get_agent
from .agents.claude import ClaudeClient
from .agents.gemini import GeminiClient
from .roundtable_permissions import permission_manager
from .roundtable_tools import (
    WRITE_TOOL_NAMES,
    RoundtableToolExecutor,
    ToolResult,
    format_tool_results_for_prompt,
    get_default_executor,
    to_adk_function_tools,
    to_claude_sdk_tools,
)

logger = logging.getLogger(__name__)

# Type alias for permission callback
PermissionCallback = Callable[[str, dict[str, Any]], Awaitable[bool]]

# Context variable for current session ID (used by permission callback)
current_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_session_id", default=None
)


async def default_permission_callback(tool_name: str, tool_args: dict[str, Any]) -> bool:
    """Default permission callback that uses the PermissionManager.

    Uses the session_id from the current context to register the permission
    request and waits for user approval via the API.

    Args:
        tool_name: Name of the tool requesting permission
        tool_args: Arguments passed to the tool

    Returns:
        True if approved, False if denied or timed out
    """
    session_id = current_session_id.get()
    if session_id is None:
        logger.warning(
            "Permission callback called without session_id context, denying"
        )
        return False

    return await permission_manager.request_permission(
        session_id=session_id,
        tool_name=tool_name,
        tool_args=tool_args,
    )

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
    """Active roundtable session with conversation history.

    Agents have read-only codebase access via tools by default.
    Additional tool permissions can be granted per session.
    """

    id: str
    project_id: str
    messages: list[RoundtableMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    mode: Literal["spec_driven", "quick"] = "quick"
    tool_executor: RoundtableToolExecutor = field(default_factory=get_default_executor)
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

    def get_effective_model(self, agent_type: AgentType, default_claude: str = "claude-sonnet-4-5", default_gemini: str = "gemini-3-flash-preview") -> str:
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

    # Tool access guidance (added when tools are enabled)
    TOOL_GUIDANCE = """
CODEBASE ACCESS:
You have READ-ONLY access to the codebase via tools. Use them to:
- Read specific files to understand existing patterns
- Search for function definitions, classes, or patterns
- Explore project structure to understand architecture

When discussing code or features:
1. USE TOOLS to verify your assumptions about the codebase
2. Reference specific files and line numbers when relevant
3. Base recommendations on actual code patterns, not generic advice
4. If unsure, search the code first before making claims

Available tools: read_file, search_code, list_files, get_project_structure
"""

    def __init__(
        self,
        claude_model: str = "claude-sonnet-4-5",
        gemini_model: str = "gemini-3-flash-preview",
        permission_callback: PermissionCallback | None = None,
    ) -> None:
        """Initialize roundtable service with model configurations.

        Args:
            claude_model: Model for Claude agent
            gemini_model: Model for Gemini agent
            permission_callback: Async callback for write tool permission prompts.
                Called with (tool_name, tool_args) when write tools need approval.
                Returns True to allow, False to deny.
        """
        self.claude_model = claude_model
        self.gemini_model = gemini_model
        self._permission_callback = permission_callback
        self._sessions: dict[str, RoundtableSession] = {}

        # Create agent clients with permission callback
        self._claude_client = ClaudeClient(
            model=claude_model,
            permission_callback=permission_callback,
        )
        self._gemini_client = GeminiClient(
            model=gemini_model,
            permission_callback=permission_callback,
        )

    def get_session(self, session_id: str) -> RoundtableSession | None:
        """Get an existing session by ID."""
        return self._sessions.get(session_id)

    def create_session(
        self,
        project_id: str,
        mode: Literal["spec_driven", "quick"] = "quick",
        tools_enabled: bool = True,
    ) -> RoundtableSession:
        """Create a new roundtable session."""
        session = RoundtableSession.create(project_id, mode, tools_enabled)
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
        session: RoundtableSession | None = None,
    ) -> LLMResponse:
        """Send message to a specific agent with context and optional tool access.

        If session has tools_enabled=True, agents can use read-only codebase tools.
        The agent may call tools multiple times before providing a final response.
        """
        model = (
            self.claude_model if agent_type == "claude" else self.gemini_model
        )
        agent = get_agent(agent_type, model=model)

        # Agent-specific identity
        agent_identity = {
            "claude": "You are CLAUDE (Anthropic). In conversation logs, you are labeled as [CLAUDE].",
            "gemini": "You are GEMINI (Google). In conversation logs, you are labeled as [GEMINI].",
        }

        # Build system prompt with identity and optional tool guidance
        tool_section = ""
        if session and session.tools_enabled:
            tool_section = self.TOOL_GUIDANCE

        system_prompt = f"""{agent_identity.get(agent_type, "")}

{self.ROUNDTABLE_SYSTEM}
{tool_section}
IMPORTANT: You are {agent_type.upper()}. Do NOT confuse yourself with the other AI assistant in this conversation."""

        # Build prompt with context
        prompt = message
        if context:
            prompt = f"""This is a multi-agent roundtable discussion. Here is the conversation so far:

{context}

The user's most recent message that you should respond to is: "{message}"

Provide your unique perspective as {agent_type.upper()}. Do not repeat what the other agent said - add new value."""

        # Check if tools are enabled
        if session and session.tools_enabled:
            return self._send_with_tools(
                agent=agent,
                prompt=prompt,
                system=system_prompt,
                session=session,
                session_id=session.id,
            )

        # No tools - simple generation
        return agent.generate(
            prompt=prompt,
            system=system_prompt,
            max_tokens=4096,
            temperature=0.7,
        )

    def _send_with_tools(
        self,
        agent: Any,
        prompt: str,
        system: str,
        session: RoundtableSession,
        max_iterations: int = 30,
        max_tool_calls: int = 100,
        detect_duplicates: bool = True,
        session_id: str | None = None,
    ) -> LLMResponse:
        """Send message with tool access, handling tool calls in a loop.

        .. deprecated::
            This method uses the legacy JSON-based tool protocol. For new code,
            use `_send_with_tools_native()` which uses Claude SDK hooks and
            Google ADK callbacks for native tool support and better session
            management.

        Uses multiple safeguards to prevent runaway agents:
        - max_iterations: Maximum rounds of tool calls (safety net)
        - max_tool_calls: Total tool calls allowed across all iterations
        - detect_duplicates: Stop if agent calls same tool with same params

        Args:
            agent: LLM client to use
            prompt: User prompt
            system: System prompt
            session: Session with tool executor
            max_iterations: Maximum tool call rounds (default 30)
            max_tool_calls: Maximum total tool calls (default 100)
            detect_duplicates: Stop on repeated identical calls (default True)
            session_id: Session ID for permission callbacks (optional)

        Returns:
            Final LLMResponse after all tool calls are complete
        """
        import warnings
        warnings.warn(
            "_send_with_tools() uses the legacy JSON protocol. "
            "Use _send_with_tools_native() for SDK-native tool support.",
            DeprecationWarning,
            stacklevel=2,
        )
        import json as json_module

        tools = session.tool_executor.get_available_tools()
        current_prompt = prompt
        conversation_history: list[dict[str, Any]] = []

        # Track tool usage for limits
        total_tool_calls = 0
        seen_calls: set[str] = set()

        for iteration in range(max_iterations):
            # Generate with tools
            response = agent.generate_with_tools(
                prompt=current_prompt,
                tools=tools,
                system=system,
                conversation_history=conversation_history,
                max_tokens=4096,
                temperature=0.7,
            )

            # If no tool calls, we're done
            if response.stop_reason != "tool_use" or not response.tool_calls:
                logger.info(
                    f"Agent completed after {iteration} iterations, "
                    f"{total_tool_calls} total tool calls"
                )
                return response

            # Execute tool calls with safety checks
            tool_results = []
            should_stop = False

            for tool_call in response.tool_calls:
                tool_name = tool_call.get("name", "")
                parameters = tool_call.get("parameters", {})

                # Check for duplicate calls (agent confusion)
                if detect_duplicates:
                    call_key = f"{tool_name}:{json_module.dumps(parameters, sort_keys=True)}"
                    if call_key in seen_calls:
                        logger.warning(
                            f"Duplicate tool call detected: {tool_name}, stopping"
                        )
                        should_stop = True
                        break
                    seen_calls.add(call_key)

                # Check tool call budget
                total_tool_calls += 1
                if total_tool_calls > max_tool_calls:
                    logger.warning(
                        f"Tool call budget exhausted ({max_tool_calls} calls)"
                    )
                    should_stop = True
                    break

                logger.info(
                    f"Executing tool [{total_tool_calls}/{max_tool_calls}]: "
                    f"{tool_name}"
                )

                # Check if this is a write tool that needs permission
                if tool_name in WRITE_TOOL_NAMES:
                    if not session.tool_executor.has_write_access():
                        # Write access not enabled - block
                        result = ToolResult(
                            success=False,
                            output="",
                            error=f"Write access not enabled for {tool_name}",
                        )
                        tool_results.append((tool_name, result))
                        continue

                    if not session.tool_executor.yolo_mode:
                        # Need to request permission
                        effective_session_id = session_id or current_session_id.get()
                        if effective_session_id and self._permission_callback:
                            # Set the context for the permission callback
                            current_session_id.set(effective_session_id)
                            # Use asyncio to run the async permission callback
                            try:
                                import asyncio
                                loop = asyncio.new_event_loop()
                                approved = loop.run_until_complete(
                                    self._permission_callback(tool_name, parameters)
                                )
                                loop.close()

                                if not approved:
                                    result = ToolResult(
                                        success=False,
                                        output="",
                                        error=f"Permission denied for {tool_name}",
                                    )
                                    tool_results.append((tool_name, result))
                                    logger.info(f"Permission denied for {tool_name}")
                                    continue

                                logger.info(f"Permission granted for {tool_name}")
                            except Exception as e:
                                logger.error(f"Permission callback error: {e}")
                                result = ToolResult(
                                    success=False,
                                    output="",
                                    error=f"Permission check failed: {e}",
                                )
                                tool_results.append((tool_name, result))
                                continue
                        else:
                            # No session context or callback - deny for safety
                            logger.warning(
                                f"No permission callback for {tool_name}, denying"
                            )
                            result = ToolResult(
                                success=False,
                                output="",
                                error="Permission required but no callback configured",
                            )
                            tool_results.append((tool_name, result))
                            continue

                result = session.tool_executor.execute(tool_name, parameters)
                tool_results.append((tool_name, result))

                logger.info(
                    f"Tool {tool_name} result: success={result.success}, "
                    f"output_len={len(result.output)}"
                )

                # Capture observation (fire-and-forget)
                if result.success:
                    self._capture_observation(
                        project_id=session.project_id,
                        session_id=session.id,
                        agent_type=session.agent_override or "unknown",
                        tool_name=tool_name,
                        tool_input=parameters,
                        tool_output=result.output,
                    )

            # If we hit a limit, return current response
            if should_stop:
                return response

            # Add to conversation history
            conversation_history.append({
                "role": "assistant",
                "content": response.content,
            })

            # Format tool results for next prompt
            results_text = format_tool_results_for_prompt(tool_results)
            conversation_history.append({
                "role": "user",
                "content": f"Tool results:\n\n{results_text}\n\nContinue with your analysis.",
            })

            # Update prompt for next iteration
            current_prompt = (
                f"You called the following tools. Here are the results:\n\n"
                f"{results_text}\n\n"
                f"Based on these results, continue your analysis. "
                f"If you need more information, call additional tools. "
                f"When you have enough information, provide your final response as plain text."
            )

        # Max iterations reached
        logger.warning(
            f"Agent reached max iterations ({max_iterations}), "
            f"{total_tool_calls} tool calls made"
        )
        return response

    async def _send_with_tools_native(
        self,
        agent_type: AgentType,
        prompt: str,
        system: str,
        session: RoundtableSession,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Send message with native SDK tool calling.

        Uses Claude SDK hooks or Google ADK callbacks for tool permission
        control instead of custom JSON protocol.

        Args:
            agent_type: Which agent to use ("claude" or "gemini")
            prompt: User prompt
            system: System prompt
            session: Session with tool executor

        Yields:
            Event dicts with message content, tool calls, and captured SDK session IDs
        """
        from app.storage import roundtable as roundtable_storage

        tools = session.tool_executor.get_available_tools()
        write_enabled = session.tool_executor.has_write_access()
        yolo_mode = session.tool_executor.yolo_mode

        if agent_type == "claude":
            # Use Claude's native SDK with PreToolUse hooks
            # Pass existing session ID for resume if available
            sdk_tools = to_claude_sdk_tools(tools)
            async for event, sdk_session_id in self._claude_client.generate_with_tools_native(
                prompt=prompt,
                tools=sdk_tools,
                system=system,
                write_enabled=write_enabled,
                yolo_mode=yolo_mode,
                session_id=session.claude_sdk_session_id,
            ):
                # Capture and persist SDK session ID if we got a new one
                if sdk_session_id and sdk_session_id != session.claude_sdk_session_id:
                    session.claude_sdk_session_id = sdk_session_id
                    roundtable_storage.update_sdk_session_ids(
                        session_id=session.id,
                        claude_sdk_session_id=sdk_session_id,
                    )
                    logger.info(f"Persisted Claude SDK session ID: {sdk_session_id}")

                yield {"agent": "claude", "event": event, "sdk_session_id": sdk_session_id}

        else:  # gemini
            # Use Google ADK with before_tool_callback
            # Pass existing session ID for resume if available
            adk_tools = to_adk_function_tools(tools, session.tool_executor)
            async for event, gemini_session_id in self._gemini_client.generate_with_tools_native(
                prompt=prompt,
                tools=adk_tools,
                system=system,
                write_enabled=write_enabled,
                yolo_mode=yolo_mode,
                session_id=session.gemini_sdk_session_id,
            ):
                # Capture and persist Gemini session ID if we got a new one
                if gemini_session_id and gemini_session_id != session.gemini_sdk_session_id:
                    session.gemini_sdk_session_id = gemini_session_id
                    roundtable_storage.update_sdk_session_ids(
                        session_id=session.id,
                        gemini_sdk_session_id=gemini_session_id,
                    )
                    logger.info(f"Persisted Gemini SDK session ID: {gemini_session_id}")

                yield {"agent": "gemini", "event": event, "sdk_session_id": gemini_session_id}

    async def route_message_with_native_tools(
        self,
        session: RoundtableSession,
        message: str,
        target: TargetAgent = "both",
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Route message using native SDK tool calling with permission callbacks.

        This is the new SDK-native method that replaces the custom JSON protocol.
        Uses Claude SDK hooks and Google ADK callbacks for tool permissions.

        Args:
            session: The roundtable session
            message: User's message
            target: Target agent ("claude", "gemini", or "both")

        Yields:
            Event dicts containing agent responses and tool calls
        """
        # Add user message to session
        user_msg = RoundtableMessage.create("user", message)
        session.add_message(user_msg)

        # Build context and prompts
        context = session.get_context()

        # Build system prompt with identity
        def build_system_prompt(agent_type: str) -> str:
            agent_identity = {
                "claude": "You are CLAUDE (Anthropic). In conversation logs, you are labeled as [CLAUDE].",
                "gemini": "You are GEMINI (Google). In conversation logs, you are labeled as [GEMINI].",
            }
            tool_section = self.TOOL_GUIDANCE if session.tools_enabled else ""
            return f"""{agent_identity.get(agent_type, "")}

{self.ROUNDTABLE_SYSTEM}
{tool_section}
IMPORTANT: You are {agent_type.upper()}. Do NOT confuse yourself with the other AI assistant in this conversation."""

        # Build prompt with context
        def build_prompt(user_message: str) -> str:
            if not context:
                return user_message
            return f"""This is a multi-agent roundtable discussion. Here is the conversation so far:

{context}

The user's most recent message that you should respond to is: "{user_message}"

Provide your unique perspective. Do not repeat what the other agent said - add new value."""

        prompt = build_prompt(message)

        if target in ("claude", "both"):
            system = build_system_prompt("claude")
            async for event in self._send_with_tools_native("claude", prompt, system, session):
                yield event

        if target in ("gemini", "both"):
            # Update context if Claude already responded
            if target == "both":
                context_updated = session.get_context()
                prompt = build_prompt(message) if context == context_updated else f"""This is a multi-agent roundtable discussion. Here is the conversation so far:

{context_updated}

The user's most recent message that you should respond to is: "{message}"

Provide your unique perspective. Do not repeat what the other agent said - add new value."""

            system = build_system_prompt("gemini")
            async for event in self._send_with_tools_native("gemini", prompt, system, session):
                yield event

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

    # =========================================================================
    # Observation Capture
    # =========================================================================

    def _capture_observation(
        self,
        project_id: str,
        session_id: str,
        agent_type: str,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_output: str,
    ) -> None:
        """Fire-and-forget observation capture for tool executions.

        Enqueues tool execution for async observation extraction.
        Does not block on failure - logs errors but continues.
        """
        try:
            from .memory import ObservationQueue

            queue = ObservationQueue()

            # Run async enqueue in a new event loop (we're in sync context)
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(
                    queue.enqueue(
                        project_id=project_id,
                        session_id=session_id,
                        agent_type=agent_type,
                        tool_name=tool_name,
                        tool_input=tool_input,
                        tool_output=tool_output,
                    )
                )
            finally:
                loop.close()
        except Exception as e:
            # Don't break roundtable for observation capture failures
            logger.warning(f"Failed to capture observation: {e}")

    # =========================================================================
    # Prompt Configuration
    # =========================================================================

    def get_effective_prompt(
        self, project_id: str, prompt_type: str
    ) -> dict[str, Any]:
        """Get the effective prompt for a project (custom or default).

        Args:
            project_id: Project ID
            prompt_type: Type of prompt (feature_extraction, vision_extraction, goals_extraction)

        Returns:
            Prompt configuration dict with prompt_text, primary_agent, primary_model, etc.
        """
        from app.storage import extraction_prompts

        prompt = extraction_prompts.get_extraction_prompt(project_id, prompt_type)
        if prompt:
            return prompt

        # Fallback to class-level defaults (legacy)
        if prompt_type == "feature_extraction":
            return {
                "prompt_text": self.FEATURE_EXTRACTION_PROMPT,
                "primary_agent": "gemini",
                "primary_model": "gemini-3-flash-preview",
                "verification_enabled": False,
                "is_default": True,
            }
        elif prompt_type == "vision_extraction":
            return {
                "prompt_text": self.VISION_EXTRACTION_PROMPT,
                "primary_agent": "claude",
                "primary_model": "claude-sonnet-4-5",
                "verification_enabled": False,
                "is_default": True,
            }
        elif prompt_type == "goals_extraction":
            return {
                "prompt_text": self.GOALS_EXTRACTION_PROMPT,
                "primary_agent": "claude",
                "primary_model": "claude-sonnet-4-5",
                "verification_enabled": False,
                "is_default": True,
            }

        return {"prompt_text": "", "primary_agent": "claude", "is_default": True}

    # =========================================================================
    # Spec-Driven Mode: Feature Extraction
    # =========================================================================

    FEATURE_EXTRACTION_PROMPT = """Analyze the following Roundtable conversation and extract any features that were discussed, designed, or planned.

For each feature, provide:
1. A clear, concise name (title)
2. A description of what the feature should do
3. A category (e.g., "ui", "backend", "api", "database", "auth", "integration")
4. Priority (1=critical, 2=high, 3=medium, 4=low, 5=nice-to-have)
5. A list of acceptance criteria - specific, testable conditions that must be true for the feature to be complete

IMPORTANT: Return ONLY valid JSON in this exact format:
{
  "features": [
    {
      "name": "Feature Title",
      "description": "Detailed description of the feature",
      "category": "category_name",
      "priority": 3,
      "acceptance_criteria": [
        {"id": "ac-001", "description": "When X happens, Y should be true"},
        {"id": "ac-002", "description": "User can do Z"}
      ]
    }
  ]
}

If no features were discussed, return: {"features": []}

CONVERSATION:
"""

    # =========================================================================
    # Vision Extraction
    # =========================================================================

    VISION_EXTRACTION_PROMPT = """Analyze the following Roundtable conversation and extract the project's vision, mission, and key narratives that were discussed.

Extract:
1. A mission statement - the core purpose and value proposition of the project
2. Key values that emerged from the discussion (optional)
3. Narratives - distinct vision themes or perspectives discussed (like "what the project is", "why it matters", "how it works")

IMPORTANT: Return ONLY valid JSON in this exact format:
{
  "mission": {
    "statement": "Clear, concise mission statement capturing the project's purpose",
    "values": ["value1", "value2"]
  },
  "narratives": [
    {
      "id": "narrative-1",
      "title": "Narrative Title",
      "content": "Detailed narrative content capturing this aspect of the vision",
      "category": "what|why|how|who|principles"
    }
  ]
}

Categories for narratives:
- "what": What the project is/does
- "why": Why it matters, problems it solves
- "how": How it works, approach
- "who": Target users, stakeholders
- "principles": Core principles, values in action

If no vision was discussed, return: {"mission": null, "narratives": []}

CONVERSATION:
"""

    # =========================================================================
    # Goals Extraction
    # =========================================================================

    GOALS_EXTRACTION_PROMPT = """Analyze the following Roundtable conversation and extract high-level strategic goals that were discussed for the project.

Goals are high-level objectives that features can be linked to. They represent the "why" behind features.

For each goal, provide:
1. A unique code (format: VG-XXX where XXX is a short identifier like PERF, UX, SEC, AUTO)
2. A clear, concise name
3. A description explaining what achieving this goal means
4. A category (e.g., "performance", "usability", "security", "automation", "scalability", "integration")

IMPORTANT: Return ONLY valid JSON in this exact format:
{
  "goals": [
    {
      "code": "VG-PERF",
      "name": "Performance Optimization",
      "description": "Ensure the system responds quickly and handles load efficiently",
      "category": "performance"
    }
  ]
}

If no goals were discussed, return: {"goals": []}

CONVERSATION:
"""

    def extract_vision_from_conversation(
        self,
        session: RoundtableSession,
        agent_type: AgentType = "claude",
    ) -> dict:
        """Extract vision (mission + narratives) from a Roundtable conversation.

        Uses configurable prompts from DB if available. Falls back to defaults.
        Uses session's agent_override if set, otherwise uses prompt's primary_agent.

        Args:
            session: The roundtable session to analyze
            agent_type: Which agent to use for extraction (default, may be overridden)

        Returns:
            Dict with 'mission' and 'narratives' keys
        """
        import json as json_module
        import re

        context = session.get_context(max_messages=50)

        # Get effective prompt config (custom or default)
        prompt_config = self.get_effective_prompt(session.project_id, "vision_extraction")
        prompt_text = prompt_config.get("prompt_text", self.VISION_EXTRACTION_PROMPT)

        # Use session override > prompt config > provided agent_type
        if session.agent_override:
            effective_agent = session.agent_override
        else:
            effective_agent = prompt_config.get("primary_agent", agent_type)

        effective_model = session.get_effective_model(
            effective_agent, self.claude_model, self.gemini_model
        )
        agent = get_agent(effective_agent, model=effective_model)
        logger.info(f"Vision extraction using agent={effective_agent}, model={effective_model}")

        prompt = prompt_text + "\n\nCONVERSATION:\n" + context

        try:
            response = agent.generate(
                prompt=prompt,
                system="You are a vision and strategy analyst. Extract structured vision content from conversations.",
                max_tokens=8192,
                temperature=0.3,
            )

            content = response.content.strip()

            # Try to extract JSON from markdown code blocks
            json_match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
            if json_match:
                content = json_match.group(1)

            data = json_module.loads(content)
            return {
                "mission": data.get("mission"),
                "narratives": data.get("narratives", []),
            }

        except Exception as e:
            logger.error(f"Vision extraction failed: {e}")
            return {"mission": None, "narratives": []}

    def extract_goals_from_conversation(
        self,
        session: RoundtableSession,
        agent_type: AgentType = "claude",
    ) -> list[dict]:
        """Extract strategic goals from a Roundtable conversation.

        Uses configurable prompts from DB if available. Falls back to defaults.
        Uses session's agent_override if set, otherwise uses prompt's primary_agent.

        Args:
            session: The roundtable session to analyze
            agent_type: Which agent to use for extraction (default, may be overridden)

        Returns:
            List of extracted goal dicts
        """
        import json as json_module
        import re

        context = session.get_context(max_messages=50)

        # Get effective prompt config (custom or default)
        prompt_config = self.get_effective_prompt(session.project_id, "goals_extraction")
        prompt_text = prompt_config.get("prompt_text", self.GOALS_EXTRACTION_PROMPT)

        # Use session override > prompt config > provided agent_type
        if session.agent_override:
            effective_agent = session.agent_override
        else:
            effective_agent = prompt_config.get("primary_agent", agent_type)

        effective_model = session.get_effective_model(
            effective_agent, self.claude_model, self.gemini_model
        )
        agent = get_agent(effective_agent, model=effective_model)
        logger.info(f"Goals extraction using agent={effective_agent}, model={effective_model}")

        prompt = prompt_text + "\n\nCONVERSATION:\n" + context

        try:
            response = agent.generate(
                prompt=prompt,
                system="You are a strategic planning analyst. Extract structured goals from conversations.",
                max_tokens=4096,
                temperature=0.3,
            )

            content = response.content.strip()

            json_match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
            if json_match:
                content = json_match.group(1)

            data = json_module.loads(content)
            return data.get("goals", [])

        except Exception as e:
            logger.error(f"Goals extraction failed: {e}")
            return []

    def extract_features_from_conversation(
        self,
        session: RoundtableSession,
        agent_type: AgentType = "claude",
    ) -> list[dict]:
        """Extract features from a Roundtable conversation.

        Uses configurable prompts from DB if available. Falls back to defaults.
        Uses session's agent_override if set, otherwise uses prompt's primary_agent.

        Args:
            session: The roundtable session to analyze
            agent_type: Which agent to use for extraction (default, may be overridden)

        Returns:
            List of extracted feature dicts ready for creation
        """
        import json as json_module
        import re

        # Build conversation transcript
        context = session.get_context(max_messages=50)

        # Get effective prompt config (custom or default)
        prompt_config = self.get_effective_prompt(session.project_id, "feature_extraction")
        prompt_text = prompt_config.get("prompt_text", self.FEATURE_EXTRACTION_PROMPT)

        # Use session override > prompt config > provided agent_type
        if session.agent_override:
            effective_agent = session.agent_override
        else:
            effective_agent = prompt_config.get("primary_agent", agent_type)

        effective_model = session.get_effective_model(
            effective_agent, self.claude_model, self.gemini_model
        )
        agent = get_agent(effective_agent, model=effective_model)
        logger.info(f"Feature extraction using agent={effective_agent}, model={effective_model}")

        prompt = prompt_text + "\n\nCONVERSATION:\n" + context

        try:
            response = agent.generate(
                prompt=prompt,
                system="You are a feature extraction specialist. Extract structured feature definitions from conversations.",
                max_tokens=8192,
                temperature=0.3,  # Lower temperature for more consistent JSON
            )

            # Parse JSON from response
            content = response.content.strip()

            # Try to extract JSON from markdown code blocks
            json_match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
            if json_match:
                content = json_match.group(1)

            data = json_module.loads(content)
            return data.get("features", [])

        except Exception as e:
            logger.error(f"Feature extraction failed: {e}")
            return []

    def create_features_from_conversation(
        self,
        session: RoundtableSession,
        agent_type: AgentType = "gemini",
    ) -> list[dict]:
        """Extract features from conversation and create them in the database.

        This is the main method for Spec-Driven mode output.

        Args:
            session: The roundtable session to analyze
            agent_type: Which agent to use for extraction

        Returns:
            List of created feature dicts with IDs
        """
        from app.storage import features as feature_storage

        # Extract features from conversation
        extracted = self.extract_features_from_conversation(session, agent_type)

        if not extracted:
            logger.info("No features extracted from conversation")
            return []

        created_features = []

        for feat in extracted:
            # Get next feature ID
            feature_id = feature_storage.get_next_feature_id(session.project_id)

            # Prepare acceptance criteria with IDs if not present
            criteria = []
            for i, crit in enumerate(feat.get("acceptance_criteria", [])):
                criterion = {
                    "id": crit.get("id", f"ac-{i+1:03d}"),
                    "description": crit.get("description", ""),
                    "passes": False,
                    "verified_at": None,
                    "evidence_id": None,
                }
                criteria.append(criterion)

            # Create feature in database
            created = feature_storage.create_feature(
                project_id=session.project_id,
                feature_id=feature_id,
                name=feat.get("name", "Untitled Feature"),
                category=feat.get("category", "feature"),
                description=feat.get("description", ""),
                acceptance_criteria=criteria,
                priority=feat.get("priority", 3),
            )

            if created:
                created_features.append(created)
                logger.info(f"Created feature {feature_id}: {created['name']}")
            else:
                logger.warning(f"Failed to create feature: {feat.get('name')}")

        return created_features


# Module-level singleton for convenience
_roundtable_service: RoundtableService | None = None


def get_roundtable_service() -> RoundtableService:
    """Get or create the roundtable service singleton.

    The singleton is created with the default permission callback that
    uses the PermissionManager for user approval prompts.
    """
    global _roundtable_service
    if _roundtable_service is None:
        _roundtable_service = RoundtableService(
            permission_callback=default_permission_callback,
        )
    return _roundtable_service
