"""Failure classification for recovery system.

Classifies test failures into types for appropriate recovery strategies.
"""

from __future__ import annotations

import re
from enum import Enum


class FailureType(Enum):
    """Types of build/test failures."""

    BROKEN_BUILD = "broken_build"  # Code won't compile/import
    VERIFICATION_FAILED = "verification_failed"  # Test assertions failed
    CIRCULAR_FIX = "circular_fix"  # Same error repeating
    CONTEXT_EXHAUSTED = "context_exhausted"  # LLM context limit reached
    TIMEOUT = "timeout"  # Test/build timed out
    UNKNOWN = "unknown"  # Unclassified failure


class RecoveryStrategy(Enum):
    """Strategies for recovering from failures."""

    RETRY = "retry"  # Try again with same approach
    ROLLBACK = "rollback"  # Revert to last good commit
    EXPAND_CONTEXT = "expand_context"  # Provide more context to agent
    SIMPLIFY = "simplify"  # Break down into smaller changes
    ESCALATE = "escalate"  # Stop and request human intervention


# Patterns for failure classification
BROKEN_BUILD_PATTERNS = [
    r"ImportError",
    r"ModuleNotFoundError",
    r"SyntaxError",
    r"NameError",
    r"AttributeError.*has no attribute",
    r"IndentationError",
    r"TypeError.*argument",
    r"cannot import name",
]

VERIFICATION_PATTERNS = [
    r"AssertionError",
    r"assert.*failed",
    r"Expected.*but got",
    r"FAILED",
    r"pytest.*failed",
    r"vitest.*fail",
]

TIMEOUT_PATTERNS = [
    r"TimeoutError",
    r"timeout",
    r"timed out",
    r"Timeout:",
]


def classify_failure(
    test_output: str | None = None,
    error_text: str | None = None,
) -> FailureType:
    """Classify a test/build failure into a failure type.

    Args:
        test_output: Raw test output
        error_text: Error message or exception text

    Returns:
        FailureType enum value.
    """
    # Combine inputs for pattern matching
    text = ""
    if test_output:
        text += test_output
    if error_text:
        text += "\n" + error_text

    if not text.strip():
        return FailureType.UNKNOWN

    # Check timeout first (often appears alongside other errors)
    for pattern in TIMEOUT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return FailureType.TIMEOUT

    # Check for broken build (import/syntax errors)
    for pattern in BROKEN_BUILD_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return FailureType.BROKEN_BUILD

    # Check for verification failures (test assertions)
    for pattern in VERIFICATION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return FailureType.VERIFICATION_FAILED

    return FailureType.UNKNOWN


def get_recovery_strategy(
    failure_type: FailureType,
    attempt_count: int,
    is_circular: bool = False,
) -> RecoveryStrategy:
    """Get the recommended recovery strategy for a failure.

    Args:
        failure_type: Type of failure
        attempt_count: Number of attempts so far
        is_circular: Whether this is a detected circular fix

    Returns:
        RecoveryStrategy enum value.
    """
    # Circular fixes always escalate
    if is_circular:
        return RecoveryStrategy.ESCALATE

    # Context exhaustion needs special handling
    if failure_type == FailureType.CONTEXT_EXHAUSTED:
        return RecoveryStrategy.EXPAND_CONTEXT

    # After 3 attempts, try rollback
    if attempt_count >= 3:
        return RecoveryStrategy.ROLLBACK

    # First few attempts: retry
    if attempt_count < 2:
        return RecoveryStrategy.RETRY

    # Middle attempts: try simplifying
    if failure_type == FailureType.VERIFICATION_FAILED:
        return RecoveryStrategy.SIMPLIFY

    return RecoveryStrategy.RETRY
