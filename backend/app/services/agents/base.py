"""Base classes for LLM agent clients."""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Standardized LLM response across all providers."""

    content: str
    provider: str  # 'claude' or 'gemini'
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    stop_reason: str = "end_turn"  # 'end_turn', 'tool_use', 'max_tokens'
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw_response: dict[str, Any] = field(default_factory=dict)


class LLMClient(ABC):
    """Abstract base class for LLM providers.

    Implementations should use CLI tools (not API keys) for authentication.
    Both Claude and Gemini CLIs handle auth via local credential caching.
    """

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate completion.

        Args:
            prompt: User prompt
            system: System prompt (optional)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Provider-specific options

        Returns:
            LLMResponse with content and metadata

        Raises:
            RuntimeError: If generation fails
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider is available and operational.

        Returns:
            True if provider can be used, False otherwise
        """
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Get the model identifier used by this client.

        Returns:
            Model name string
        """
        pass

    def authenticate(self) -> bool:
        """Verify authentication is working.

        For CLI-based providers, this checks:
        1. CLI executable exists in PATH
        2. CLI can execute (cached credentials valid)

        Returns:
            True if authenticated, False otherwise
        """
        return self.is_available()

    def send_message(
        self,
        message: str,
        system: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Send a message and get response text.

        Simplified interface for basic chat interactions.

        Args:
            message: User message
            system: System prompt (optional)
            **kwargs: Additional options passed to generate()

        Returns:
            Response text content

        Raises:
            RuntimeError: If generation fails
        """
        response = self.generate(prompt=message, system=system, **kwargs)
        return response.content

    def generate_with_tools(
        self,
        prompt: str,
        tools: list[dict[str, Any]],
        system: str | None = None,
        conversation_history: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate with tool calling support (JSON-based protocol).

        .. deprecated::
            This method uses a custom JSON-based tool protocol and is deprecated.
            Use ``generate_with_tools_native()`` instead, which uses SDK-native
            tool calling with proper permission hooks.

            This method is kept as a fallback for edge cases where native SDK
            tool calling is unavailable.

        This method implements a JSON-based tool calling protocol that works
        with CLI providers that don't support native tool calling.

        The protocol:
        1. Formats tool definitions into system prompt
        2. Instructs model to respond with JSON when calling tools
        3. Parses response for tool calls
        4. Returns LLMResponse with stop_reason="tool_use" or "end_turn"

        Args:
            prompt: User prompt or tool results from previous turn
            tools: Tool definitions in Anthropic API format
            system: Base system prompt (tools will be appended)
            conversation_history: Previous turns (optional, for context)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Provider-specific options

        Returns:
            LLMResponse with:
              - stop_reason: "tool_use" if tools called, "end_turn" if done
              - tool_calls: List of {"name": ..., "parameters": ...}
              - content: Raw response text
        """
        # DEPRECATED: This method uses custom JSON protocol.
        # Use generate_with_tools_native() for SDK-native tool calling.
        # Kept for fallback/legacy compatibility only.
        import warnings

        warnings.warn(
            "generate_with_tools() is deprecated and uses a custom JSON protocol. "
            "Use generate_with_tools_native() for SDK-native tool calling with "
            "proper permission hooks and session management.",
            DeprecationWarning,
            stacklevel=2,
        )

        # Format system prompt with tool definitions
        system_with_tools = self._format_system_with_tools(system, tools)

        # Add conversation history context if provided
        full_prompt = prompt
        if conversation_history:
            history_parts = []
            for turn in conversation_history[-5:]:
                role = turn.get("role", "user")
                content = turn.get("content", "")
                history_parts.append(f"[{role.upper()}]: {content[:500]}")
            full_prompt = "\n".join(history_parts) + f"\n\n[USER]: {prompt}"

        # Generate response
        response = self.generate(
            prompt=full_prompt,
            system=system_with_tools,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

        # Parse for tool calls
        tool_calls = self._parse_tool_calls(response.content)

        if tool_calls:
            return LLMResponse(
                content=response.content,
                provider=response.provider,
                model=response.model,
                usage=response.usage,
                stop_reason="tool_use",
                tool_calls=tool_calls,
                raw_response=response.raw_response,
            )

        return LLMResponse(
            content=response.content,
            provider=response.provider,
            model=response.model,
            usage=response.usage,
            stop_reason="end_turn",
            tool_calls=[],
            raw_response=response.raw_response,
        )

    def _format_system_with_tools(self, system: str | None, tools: list[dict[str, Any]]) -> str:
        """Format system prompt with tool definitions."""
        tool_descriptions = []
        for tool in tools:
            schema = tool.get("input_schema", {})
            properties = schema.get("properties", {})
            required = schema.get("required", [])

            params = []
            if properties:
                for param_name, param_def in properties.items():
                    is_required = param_name in required
                    param_type = param_def.get("type", "any")
                    param_desc = param_def.get("description", "")
                    default = param_def.get("default", "")
                    default_str = f", default={default}" if default else ""

                    params.append(
                        f"  - {param_name} ({param_type}, "
                        f"{'required' if is_required else 'optional'}{default_str}): "
                        f"{param_desc}"
                    )
            else:
                params.append("  (no parameters)")

            tool_descriptions.append(
                f"TOOL: {tool['name']}\n"
                f"DESCRIPTION: {tool.get('description', '')}\n"
                f"PARAMETERS:\n" + "\n".join(params)
            )

        tools_section = "\n\n".join(tool_descriptions)

        return f"""{system or "You are a helpful AI assistant."}

You have access to these tools:

{tools_section}

To call a tool, respond with JSON in this EXACT format:
{{
  "tool_calls": [
    {{
      "name": "tool_name",
      "parameters": {{"param": "value"}}
    }}
  ]
}}

RULES:
1. ALWAYS use tools to get real data - do not hallucinate
2. You can call multiple tools by adding more objects to the array
3. After tools execute, you'll receive results to analyze
4. When done, provide your final answer as PLAIN TEXT (not JSON)
5. Only call tools defined above with required parameters
"""

    def _parse_tool_calls(self, response_text: str) -> list[dict[str, Any]]:
        """Parse response text for tool calls.

        Tries multiple strategies:
        1. Parse entire response as JSON
        2. Extract JSON from markdown code blocks
        3. Extract JSON with regex patterns
        """
        # Strategy 1: Try to parse entire response as JSON
        try:
            data = json.loads(response_text.strip())
            if isinstance(data, dict) and "tool_calls" in data:
                tool_calls = data["tool_calls"]
                if isinstance(tool_calls, list):
                    return tool_calls
        except json.JSONDecodeError:
            pass

        # Strategy 2: Extract JSON from markdown code blocks
        json_patterns = [
            r"```json\s*(.*?)\s*```",
            r"```\s*({\s*\"tool_calls\".*?})\s*```",
        ]

        for pattern in json_patterns:
            match = re.search(pattern, response_text, re.DOTALL | re.IGNORECASE)
            if match:
                try:
                    data = json.loads(match.group(1))
                    if isinstance(data, dict) and "tool_calls" in data:
                        tool_calls = data["tool_calls"]
                        if isinstance(tool_calls, list):
                            return tool_calls
                except json.JSONDecodeError:
                    continue

        # Strategy 3: Direct JSON object search
        json_match = re.search(r"(\{\s*\"tool_calls\".*?\}\s*)\s*$", response_text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                if isinstance(data, dict) and "tool_calls" in data:
                    tool_calls = data["tool_calls"]
                    if isinstance(tool_calls, list):
                        return tool_calls
            except json.JSONDecodeError:
                pass

        return []
