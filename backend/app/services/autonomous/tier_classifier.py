"""Tier classifier and model selector for autonomous execution.

Classifies tasks into tiers based on complexity and selects appropriate
AI models for execution.

Tiers:
- 1: Small tasks (<10 complexity, <300 LOC, <=1 file)
- 2: Medium tasks (<20 complexity, <600 LOC, <=5 files)
- 3: Large tasks (<30 complexity, <1000 LOC)
- 4: Architecture/multi-domain tasks (everything else)
"""

from __future__ import annotations

from typing import Any, TypedDict


class ModelConfig(TypedDict):
    """Configuration for an AI model."""

    provider: str  # 'claude' or 'gemini'
    model: str  # Model identifier
    max_tokens: int
    description: str


# Model configurations by tier and mode
AUTONOMOUS_MODELS: dict[int, ModelConfig] = {
    1: {
        "provider": "gemini",
        "model": "gemini-2.0-flash-exp",
        "max_tokens": 8192,
        "description": "Fast execution for small tasks",
    },
    2: {
        "provider": "gemini",
        "model": "gemini-2.0-flash-thinking-exp-1219",
        "max_tokens": 32768,
        "description": "Thinking model for medium tasks",
    },
    3: {
        "provider": "gemini",
        "model": "gemini-exp-1206",
        "max_tokens": 65536,
        "description": "Full context for large tasks",
    },
    4: {
        "provider": "claude",
        "model": "claude-sonnet-4-5-20250514",
        "max_tokens": 64000,
        "description": "Claude for architecture/multi-domain",
    },
}

MANUAL_MODEL: ModelConfig = {
    "provider": "claude",
    "model": "claude-sonnet-4-5-20250514",
    "max_tokens": 64000,
    "description": "Claude Sonnet for manual /do_it execution",
}

REVIEW_MODEL: ModelConfig = {
    "provider": "claude",
    "model": "claude-opus-4-5-20251101",
    "max_tokens": 32000,
    "description": "Claude Opus for review gate",
}


def classify_tier(target: dict[str, Any]) -> int:
    """Classify a task/target into an execution tier.

    Args:
        target: Dict with complexity, lines, files_count fields

    Returns:
        Tier 1-4 based on complexity thresholds
    """
    complexity = target.get("complexity", 0) or 0
    lines = target.get("lines", 0) or 0
    files_count = target.get("files_count", 1) or 1

    # Tier 1: Small
    if complexity < 10 and lines < 300 and files_count <= 1:
        return 1

    # Tier 2: Medium
    if complexity < 20 and lines < 600 and files_count <= 5:
        return 2

    # Tier 3: Large
    if complexity < 30 and lines < 1000:
        return 3

    # Tier 4: Architecture/multi-domain
    return 4


def select_model_for_tier(tier: int, manual: bool = False) -> ModelConfig:
    """Select the appropriate model for a tier.

    Args:
        tier: Execution tier (1-4)
        manual: If True, always return Claude Sonnet for better quality

    Returns:
        ModelConfig dict with provider, model, max_tokens, description
    """
    if manual:
        return MANUAL_MODEL.copy()

    return AUTONOMOUS_MODELS.get(tier, AUTONOMOUS_MODELS[4]).copy()


def get_review_model() -> ModelConfig:
    """Get the model configuration for the Opus review gate.

    Returns:
        ModelConfig for Claude Opus
    """
    return REVIEW_MODEL.copy()
