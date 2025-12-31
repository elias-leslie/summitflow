"""Autonomous execution services.

This package provides services for autonomous task execution:
- tier_classifier: Classify tasks by complexity and select appropriate models
- prompt_builder: Build execution prompts with context
- reviewer: Opus review gate
"""

from .tier_classifier import classify_tier, select_model_for_tier

__all__ = [
    "classify_tier",
    "select_model_for_tier",
]
