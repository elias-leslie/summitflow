"""Issue similarity tracking for QA review loop.

This module provides functions to identify when the same issue is being
encountered repeatedly, which triggers escalation in the QA review loop.
"""

import hashlib
import re
from difflib import SequenceMatcher

# Patterns to normalize in error messages (strip variable parts)
VARIABLE_PATTERNS = [
    (r"0x[0-9a-fA-F]+", "<addr>"),  # Memory addresses
    (r"line \d+", "line <N>"),  # Line numbers
    (r"\d{2}:\d{2}:\d{2}", "<time>"),  # Times (must be before colon pattern)
    (r":\d+:", ":<N>:"),  # File:line:col patterns
    (r"\d{4}-\d{2}-\d{2}", "<date>"),  # Dates
    (r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<uuid>"),  # UUIDs
    (r"/tmp/[^\s]+", "<tmpfile>"),  # Temp files
    (r"task-[a-z0-9]+", "task-<id>"),  # Task IDs
    (r"\d+\.\d+\.\d+\.\d+", "<ip>"),  # IP addresses
    (r"port \d+", "port <N>"),  # Port numbers
]


def normalize_error_message(error: str) -> str:
    """Normalize an error message by stripping variable parts.

    This makes it easier to compare errors that are functionally the same
    but differ in specific values like line numbers, timestamps, or IDs.

    Args:
        error: Raw error message

    Returns:
        Normalized error with variable parts replaced by placeholders.
    """
    normalized = error.strip()

    # Apply all normalization patterns
    for pattern, replacement in VARIABLE_PATTERNS:
        normalized = re.sub(pattern, replacement, normalized)

    # Collapse multiple whitespace
    normalized = re.sub(r"\s+", " ", normalized)

    return normalized


def compute_issue_id(
    error_message: str,
    verify_command: str | None = None,
    step_description: str | None = None,
) -> str:
    """Compute a stable ID for an issue based on its characteristics.

    The ID is based on:
    1. Normalized error message
    2. The verify command (if provided)
    3. The step description (if provided)

    This allows tracking the same issue across multiple attempts.

    Args:
        error_message: The error or failure message
        verify_command: The verification command that failed (optional)
        step_description: Description of the step (optional)

    Returns:
        A stable hash ID for the issue.
    """
    # Normalize the error
    normalized_error = normalize_error_message(error_message)

    # Build the components for hashing
    components = [normalized_error]
    if verify_command:
        components.append(verify_command.strip())
    if step_description:
        components.append(step_description.strip())

    # Create a stable hash
    content = "|".join(components)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def is_same_issue(
    error1: str,
    error2: str,
    threshold: float = 0.8,
) -> bool:
    """Determine if two errors represent the same underlying issue.

    Uses normalized error comparison with a similarity threshold.
    Defaults to 80% similarity to account for minor variations.

    Args:
        error1: First error message
        error2: Second error message
        threshold: Minimum similarity ratio (0.0 to 1.0, default 0.8)

    Returns:
        True if errors are similar enough to be the same issue.
    """
    # Normalize both errors
    norm1 = normalize_error_message(error1)
    norm2 = normalize_error_message(error2)

    # Exact match after normalization
    if norm1 == norm2:
        return True

    # Compute similarity ratio
    ratio = SequenceMatcher(None, norm1, norm2).ratio()

    return ratio >= threshold
