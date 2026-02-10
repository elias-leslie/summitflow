"""TDD module - Auto-suggest components and capabilities for TDD setup."""

from __future__ import annotations

# Re-export main orchestrator functions for backward compatibility
from .tdd_suggestions import (
    get_component_suggestions_by_source,
    get_tdd_suggestions,
    suggest_capabilities,
    suggest_components,
)

__all__ = [
    "get_component_suggestions_by_source",
    "get_tdd_suggestions",
    "suggest_capabilities",
    "suggest_components",
]
