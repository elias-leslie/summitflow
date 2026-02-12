"""TDD suggestions service - DEPRECATED, use tdd module instead.

This file maintained for backward compatibility.
All functionality moved to backend/app/services/tdd/ module.
"""

from __future__ import annotations

# Re-export everything from new tdd module for backward compatibility
from .tdd.capability_mapping import suggest_capabilities
from .tdd.component_grouping import suggest_components
from .tdd.coverage_analysis import get_coverage_summary
from .tdd.tdd_suggestions import (
    get_component_suggestions_by_source,
    get_tdd_suggestions,
)
from .tdd.discovery import find_existing_tests

__all__ = [
    "find_existing_tests",
    "get_component_suggestions_by_source",
    "get_coverage_summary",
    "get_tdd_suggestions",
    "suggest_capabilities",
    "suggest_components",
]
