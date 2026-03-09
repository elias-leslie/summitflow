"""Explorer context collector."""

from __future__ import annotations

from .precision_code_search import collect_precision_code_search_context
from .token_utils import MAX_EXPLORER_TOKENS


def gather_explorer_context(project_id: str, query: str) -> str:
    """Gather explorer context via shared Precision Code Search retrieval."""
    result = collect_precision_code_search_context(
        project_id,
        [query],
        budget_tokens=MAX_EXPLORER_TOKENS,
    )
    return result.prompt_context
