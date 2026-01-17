"""Context helpers service - Pattern and observation filtering for task execution.

Memory system removed - these functions now return empty lists.
Memory functionality moved to Agent Hub with Graphiti knowledge graph.
"""

from __future__ import annotations

from typing import Any


def filter_rules_by_files(files: list[str]) -> list[str]:
    """Filter rule files based on affected file paths.

    DEPRECATED: Rules consolidated into CLAUDE.md. Returns empty list.
    Kept for API backward compatibility.

    Args:
        files: List of file paths affected by a task

    Returns:
        Empty list (rules now in CLAUDE.md)
    """
    return []


def get_patterns_for_files(
    project_id: str,
    files: list[str],
    min_confidence: float = 0.7,
) -> list[dict[str, Any]]:
    """Get learned patterns relevant to the given files.

    Memory system removed - returns empty list.
    Memory functionality moved to Agent Hub with Graphiti.
    """
    return []


def get_observations_for_files(
    project_id: str,
    files: list[str],
    types: list[str] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Get recent observations relevant to the given files.

    Memory system removed - returns empty list.
    Memory functionality moved to Agent Hub with Graphiti.
    """
    return []
