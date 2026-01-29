"""Cost estimation utilities for fix agent.

Provides cost tracking for LLM usage during auto-fix attempts.
"""

from __future__ import annotations

from ...services.agent_hub_client import LLMResponse

# =============================================================================
# Cost Estimation (for budget tracking)
# =============================================================================
# Approximate costs per 1M tokens. Updated January 2026.
# These are estimates - actual billing may vary slightly.
MODEL_COSTS_PER_1M_TOKENS: dict[str, dict[str, float]] = {
    # Claude 4.5 models
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "claude-opus-4-5": {"input": 15.00, "output": 75.00},
    "claude-haiku-4-5": {"input": 0.25, "output": 1.25},
    # Gemini 3 models
    "gemini-3-flash-preview": {"input": 0.075, "output": 0.30},
    "gemini-3-pro-preview": {"input": 1.25, "output": 5.00},
}

# Default cost for unknown models (conservative estimate)
DEFAULT_COST_PER_1M = {"input": 3.00, "output": 15.00}


def estimate_cost_from_response(response: LLMResponse) -> float:
    """Estimate USD cost from an LLM response.

    Args:
        response: LLMResponse with usage dict containing token counts

    Returns:
        Estimated cost in USD
    """
    usage = response.usage
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)

    costs = MODEL_COSTS_PER_1M_TOKENS.get(response.model, DEFAULT_COST_PER_1M)

    input_cost = (input_tokens / 1_000_000) * costs["input"]
    output_cost = (output_tokens / 1_000_000) * costs["output"]

    return input_cost + output_cost
