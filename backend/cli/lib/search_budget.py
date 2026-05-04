"""Prompt budget helpers for `st search`."""

from __future__ import annotations

from app.services.context_gatherer.token_utils import estimate_tokens, truncate_to_tokens


def truncate_prompt_to_budget(text: str, budget: int) -> str:
    """Trim prompt text until the local token estimator is within the requested budget."""
    truncated = truncate_to_tokens(text, budget)
    if estimate_tokens(truncated) <= budget:
        return truncated

    best = ""
    low = 0
    high = len(truncated)
    while low <= high:
        midpoint = (low + high) // 2
        candidate = truncated[:midpoint].rstrip()
        if estimate_tokens(candidate) <= budget:
            best = candidate
            low = midpoint + 1
        else:
            high = midpoint - 1
    return best.rstrip()
