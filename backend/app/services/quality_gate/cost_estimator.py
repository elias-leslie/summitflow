"""Cost helpers for quality gate fixes.

Agent Hub owns model pricing and cost logging. SummitFlow only reads returned
telemetry when available.
"""

from __future__ import annotations

from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)

def estimate_cost_from_response(response: Any) -> float:
    """Return provider-reported cost from an Agent Hub response.

    Args:
        response: Response object from agent.generate()

    Returns:
        Cost in USD when supplied by Agent Hub, otherwise 0.0.
    """
    try:
        for attr in ("cost_usd", "cost"):
            value = getattr(response, attr, None)
            if isinstance(value, int | float):
                return float(value)

        usage = getattr(response, "usage", None)
        if isinstance(usage, dict):
            for key in ("cost_usd", "cost"):
                value = usage.get(key)
                if isinstance(value, int | float):
                    return float(value)

        raw_response = getattr(response, "raw_response", None)
        if isinstance(raw_response, dict):
            for key in ("cost_usd", "cost"):
                value = raw_response.get(key)
                if isinstance(value, int | float):
                    return float(value)
        return 0.0

    except Exception:
        logger.debug("Failed to read cost from LLM response", exc_info=True)
        return 0.0
