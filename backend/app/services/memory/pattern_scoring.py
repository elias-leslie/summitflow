"""Pattern scoring - Ranking and relevance calculations for patterns.

Handles approval boosts, observation boosts, and relevance decay calculations.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any


def parse_iso_datetime(value: str | datetime | None) -> datetime | None:
    """Parse ISO datetime string, handling Z suffix. Returns None if input is None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def get_approval_boost(pattern: dict[str, Any]) -> float:
    """Calculate approval boost multiplier for pattern ranking.

    Approved patterns get a 10% boost.
    Rejected patterns get graduated penalties:
    - 1-2 rejections: 0.9x (10% penalty)
    - 3-4 rejections: 0.7x (30% penalty)
    - 5+ rejections: 0.5x (50% penalty)

    Args:
        pattern: Pattern dict with approval_count, rejection_count, status

    Returns:
        Multiplier (0.5-1.1) to apply to pattern ranking score.
    """
    status = pattern.get("status", "pending")
    approval_count = pattern.get("approval_count", 0) or 0
    rejection_count = pattern.get("rejection_count", 0) or 0

    multiplier = 1.0

    if status in ("approved", "applied") or approval_count > 0:
        multiplier = 1.1

    if rejection_count >= 5:
        multiplier = 0.5
    elif rejection_count >= 3:
        multiplier = 0.7
    elif rejection_count >= 1:
        multiplier = 0.9

    return multiplier


def get_source_observation_boost(
    observation: dict[str, Any],
    pattern_multiplier: float = 1.0,
) -> float:
    """Apply inherited boost to source observations from approved patterns.

    When a pattern is approved, observations that sourced it get a boost.

    Args:
        observation: Observation dict (unused, kept for API compatibility)
        pattern_multiplier: Boost from the parent pattern

    Returns:
        Additional boost (0.0-0.1) to add to observation score.
    """
    if pattern_multiplier > 1.0:
        return (pattern_multiplier - 1.0) * 0.5
    return 0.0


def calculate_pattern_relevance(pattern: dict[str, Any]) -> float:
    """Calculate relevance score for a pattern based on age and usage.

    Formula: confidence * exp(-age/90) * exp(-days_unused/60)

    This produces a score that:
    - Decays as the pattern ages (half-life ~60 days)
    - Decays faster if the pattern isn't used
    - Ranges from 0.0 to ~1.0

    Used for pattern cap enforcement (lowest relevance patterns removed first).

    Args:
        pattern: Pattern dict with confidence, created_at, last_used_at

    Returns:
        Relevance score between 0.0 and 1.0.
    """
    confidence = float(pattern.get("confidence", 0.5) or 0.5)

    now = datetime.now(UTC)

    created_at = parse_iso_datetime(pattern.get("created_at"))
    if not created_at:
        created_at = now

    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)

    last_used_at = parse_iso_datetime(pattern.get("last_used_at"))
    if not last_used_at:
        last_used_at = created_at

    if last_used_at.tzinfo is None:
        last_used_at = last_used_at.replace(tzinfo=UTC)

    age_days = max(0, (now - created_at).days)
    unused_days = max(0, (now - last_used_at).days)

    age_decay = math.exp(-age_days / 90)
    usage_decay = math.exp(-unused_days / 60)

    relevance = confidence * age_decay * usage_decay

    return max(0.0, min(1.0, relevance))
