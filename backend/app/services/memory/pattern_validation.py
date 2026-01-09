"""Pattern validation - Conciseness and quality checks for patterns.

Validates that patterns are concise, specific, and free of hedging words.
"""

from __future__ import annotations

import re

MAX_TITLE_LENGTH = 100
MAX_CONTENT_LENGTH = 500
MAX_SENTENCES = 3
HEDGING_WORDS = [
    "might",
    "maybe",
    "perhaps",
    "possibly",
    "could be",
    "sometimes",
    "often",
    "usually",
    "generally",
    "typically",
]


def validate_conciseness(
    title: str,
    content: str,
) -> tuple[bool, list[str]]:
    """Validate pattern content for conciseness.

    Rules:
    - Title max 100 chars
    - Content max 500 chars
    - Max 3 sentences
    - No hedging words

    Args:
        title: Pattern title.
        content: Pattern content.

    Returns:
        Tuple of (is_valid, list of violation messages).
    """
    violations = []

    if len(title) > MAX_TITLE_LENGTH:
        violations.append(f"Title exceeds {MAX_TITLE_LENGTH} chars ({len(title)} chars)")

    if len(content) > MAX_CONTENT_LENGTH:
        violations.append(f"Content exceeds {MAX_CONTENT_LENGTH} chars ({len(content)} chars)")

    sentences = re.split(r"[.!?]+", content.strip())
    sentences = [s.strip() for s in sentences if s.strip()]
    if len(sentences) > MAX_SENTENCES:
        violations.append(f"Content has {len(sentences)} sentences (max {MAX_SENTENCES})")

    content_lower = content.lower()
    found_hedging = [w for w in HEDGING_WORDS if w in content_lower]
    if found_hedging:
        violations.append(f"Content contains hedging words: {', '.join(found_hedging)}")

    return len(violations) == 0, violations
