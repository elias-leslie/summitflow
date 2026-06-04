"""Circular fix detection.

Detects when the agent is making the same fix repeatedly,
indicating a circular pattern that won't converge.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# Common stop words to filter from error text
STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "need",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "under",
        "again",
        "further",
        "then",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "and",
        "but",
        "if",
        "or",
        "because",
        "until",
        "while",
    }
)

# Minimum keyword length to consider
MIN_KEYWORD_LENGTH = 3

# Similarity threshold for circular detection (30% = Auto-Claude pattern)
CIRCULAR_THRESHOLD = 0.30


def extract_keywords(error_text: str) -> set[str]:
    """Extract meaningful keywords from error text.

    Filters out stop words and short tokens.

    Args:
        error_text: The error message or test output

    Returns:
        Set of lowercase keywords.
    """
    if not error_text:
        return set()

    # Tokenize: split on non-alphanumeric
    tokens = re.split(r"[^a-zA-Z0-9_]+", error_text.lower())

    # Filter: remove stop words and short tokens
    keywords = {
        token for token in tokens if len(token) >= MIN_KEYWORD_LENGTH and token not in STOP_WORDS
    }

    return keywords


def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Calculate Jaccard similarity between two sets.

    Args:
        set_a: First set of strings
        set_b: Second set of strings

    Returns:
        Similarity score between 0.0 and 1.0.
    """
    if not set_a or not set_b:
        return 0.0

    intersection = len(set_a & set_b)
    union = len(set_a | set_b)

    return intersection / union if union > 0 else 0.0


def is_circular_fix(
    current_error: str,
    previous_errors: Iterable[str],
    threshold: float = CIRCULAR_THRESHOLD,
) -> bool:
    """Detect if current error is a circular fix (repeating similar error).

    Uses Jaccard similarity to compare keyword overlap.
    Returns True if any previous error has >threshold similarity.

    Args:
        current_error: Current error text
        previous_errors: List/tuple of previous error texts
        threshold: Similarity threshold (default 30%)

    Returns:
        True if circular fix detected.
    """
    current_keywords = extract_keywords(current_error)

    if not current_keywords:
        return False

    for prev_error in previous_errors:
        prev_keywords = extract_keywords(prev_error)
        similarity = jaccard_similarity(current_keywords, prev_keywords)

        if similarity >= threshold:
            return True

    return False
