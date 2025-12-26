"""Roundtable prompt building utilities.

Extracted from service.py for better modularity.
Handles agent identity prompts and system prompt construction.
"""

# Agent-specific identity strings
AGENT_IDENTITY: dict[str, str] = {
    "claude": "You are CLAUDE (Anthropic). In conversation logs, you are labeled as [CLAUDE].",
    "gemini": "You are GEMINI (Google). In conversation logs, you are labeled as [GEMINI].",
}

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


def build_system_prompt(agent_type: str, tools_enabled: bool = False) -> str:
    """Build system prompt with agent identity and optional tool guidance.

    Args:
        agent_type: "claude" or "gemini"
        tools_enabled: Whether to include tool guidance

    Returns:
        Complete system prompt string
    """
    identity = AGENT_IDENTITY.get(agent_type, "")
    tool_section = TOOL_GUIDANCE if tools_enabled else ""

    return f"""{identity}

{ROUNDTABLE_SYSTEM}
{tool_section}
IMPORTANT: You are {agent_type.upper()}. Do NOT confuse yourself with the other AI assistant in this conversation."""


def build_prompt_with_context(
    message: str, context: str | None, agent_type: str | None = None
) -> str:
    """Build user prompt with conversation context.

    Args:
        message: The user's message
        context: Previous conversation context (or None)
        agent_type: Optional agent type for perspective framing

    Returns:
        Formatted prompt string
    """
    if not context:
        return message

    perspective = ""
    if agent_type:
        perspective = f" as {agent_type.upper()}"

    return f"""This is a multi-agent roundtable discussion. Here is the conversation so far:

{context}

The user's most recent message that you should respond to is: "{message}"

Provide your unique perspective{perspective}. Do not repeat what the other agent said - add new value."""
