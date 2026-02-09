"""Token estimation and truncation utilities."""

from __future__ import annotations

# Approximate token counts (rough estimation: 4 chars = 1 token)
MAX_RULES_TOKENS = 4000
MAX_DOCS_TOKENS = 6000
MAX_MEMORY_TOKENS = 2000
MAX_EXPLORER_TOKENS = 3000
MAX_GEMINI_TOKENS = 4000
MAX_DESIGN_TOKENS = 2000
MAX_TOTAL_TOKENS = 25000


def estimate_tokens(text: str) -> int:
    """Estimate token count from text (rough: 4 chars = 1 token)."""
    return len(text) // 4


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to approximately max_tokens."""
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[... truncated ...]"
