"""TDD suggestions service - Auto-suggest components and capabilities.

Main orchestrator that combines:
- Component suggestions (from component_grouping)
- Capability mapping (from capability_mapping)
- Test discovery (from test_discovery)
- Coverage analysis (from coverage_analysis)

This service enables the /seed_tdd skill to bootstrap TDD structure.
"""

from __future__ import annotations

from typing import Any

from .capability_mapping import suggest_capabilities
from .component_grouping import suggest_components
from .coverage_analysis import generate_recommendation, get_coverage_summary
from .test_discovery import find_existing_tests


def get_tdd_suggestions(project_id: str) -> dict[str, Any]:
    """Get complete TDD suggestions for a project.

    Combines component suggestions, test discovery, and coverage stats.

    Args:
        project_id: Project ID for scoping

    Returns:
        Complete TDD suggestion response with components, tests, coverage, and recommendations
    """
    suggested_components = suggest_components(project_id)
    existing_tests = find_existing_tests(project_id)
    coverage_summary = get_coverage_summary(project_id)

    # Convert TypedDict to plain dict for compatibility
    components_dict: list[dict[str, Any]] = [dict(c) for c in suggested_components]
    tests_dict: list[dict[str, Any]] = [dict(t) for t in existing_tests]

    return {
        "suggested_components": components_dict,
        "existing_tests": tests_dict,
        "coverage_summary": coverage_summary,
        "recommendation": generate_recommendation(
            components_dict, tests_dict, coverage_summary
        ),
    }


def get_component_suggestions_by_source(project_id: str, source_type: str) -> list[dict[str, Any]]:
    """Get component suggestions filtered by source type.

    Args:
        project_id: Project ID for scoping
        source_type: One of 'pages', 'endpoints', 'directories', 'manual'

    Returns:
        List of suggested components matching the source type
    """
    if source_type == "manual":
        return []

    all_suggestions = suggest_components(project_id)

    type_map = {
        "pages": "page_group",
        "endpoints": "endpoint_group",
        "directories": "directory",
    }

    target_type = type_map.get(source_type)
    if not target_type:
        return []

    # Convert TypedDict to plain dict for compatibility
    filtered: list[dict[str, Any]] = [dict(s) for s in all_suggestions if s.get("type") == target_type]
    return filtered


# Re-export for backward compatibility (existing imports from tdd_suggestions module)
__all__ = [
    "get_component_suggestions_by_source",
    "get_tdd_suggestions",
    "suggest_capabilities",
    "suggest_components",
]
