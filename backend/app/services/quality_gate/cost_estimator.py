"""Cost estimator for quality gate fixes.

Estimates cost of LLM calls based on token usage and model pricing.
"""

from __future__ import annotations

from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)

# Pricing per 1M tokens (approximate)
PRICING = {
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-5-sonnet-20240620": {"input": 3.00, "output": 15.00},
}


def estimate_cost_from_response(response: Any) -> float:
    """Estimate cost from LLM response.

    Args:
        response: Response object from agent.generate()

    Returns:
        Estimated cost in USD
    """
    try:
        model = getattr(response, "model", "unknown")
        usage = getattr(response, "usage", None)

        if not usage:
            return 0.0

        input_tokens = getattr(usage, "input_tokens", 0)
        output_tokens = getattr(usage, "output_tokens", 0)

        # Normalize model name for lookup
        model_key = next((k for k in PRICING if k in model), None)

        if not model_key:
            # Fallback for unknown models (assume cheap)
            return (input_tokens + output_tokens) * 0.0000001

        prices = PRICING[model_key]
        input_cost = (input_tokens / 1_000_000) * prices["input"]
        output_cost = (output_tokens / 1_000_000) * prices["output"]

        return input_cost + output_cost

    except Exception:
        logger.debug("Failed to estimate cost from LLM response", exc_info=True)
        return 0.0
