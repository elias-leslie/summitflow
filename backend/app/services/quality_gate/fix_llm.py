"""LLM interaction for fix agent.

Handles LLM calls and response processing for fix attempts.
"""

from __future__ import annotations

from ...logging_config import get_logger
from ...services.agent_hub_client import get_agent
from .cost_estimator import estimate_cost_from_response

logger = get_logger(__name__)


def execute_llm_fix(
    prompt: str,
    agent_slug: str,
    temperature: float,
    result_id: int,
) -> tuple[str, float]:
    """Execute LLM fix attempt.

    Args:
        prompt: Prompt for the LLM
        agent_slug: Agent slug ('worker' or 'supervisor')
        temperature: Temperature setting
        result_id: Result ID for logging

    Returns:
        Tuple of (new_content, cost_usd)

    Raises:
        Exception: If LLM call fails
    """
    agent = get_agent(agent_slug)
    response = agent.generate(
        prompt=prompt,
        system="You are a code fix agent. Output only the fixed code, no explanations.",
        temperature=temperature,
        purpose="quality_gate_fix",
    )
    new_content = response.content.strip()
    cost_usd = estimate_cost_from_response(response)
    logger.debug("fix_attempt_cost", cost_usd=cost_usd, agent_slug=agent_slug)
    return (new_content, cost_usd)


def is_cannot_fix_response(content: str) -> tuple[bool, str]:
    """Check if response is a CANNOT_FIX response.

    Args:
        content: LLM response content

    Returns:
        Tuple of (is_cannot_fix, reason)
    """
    if content.startswith("CANNOT_FIX:"):
        return (True, content[11:].strip())
    return (False, "")
