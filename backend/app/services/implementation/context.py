"""Implementation context - Context building for task execution.

Memory system removed - patterns and observations now in Agent Hub with Graphiti.
Rules consolidated into CLAUDE.md.
"""

from __future__ import annotations

from typing import Any


def build_context(project_id: str, files: list[str]) -> dict[str, Any]:
    """Build context for a task based on affected files.

    Memory system removed - returns empty patterns/observations.
    Rules consolidated into CLAUDE.md.

    Args:
        project_id: Project ID
        files: List of affected file paths

    Returns:
        Dict with files, rules, rule_contents, patterns, observations
    """
    return {
        "files": files,
        "rules": [],
        "rule_contents": {},
        "patterns": [],  # Memory system removed
        "observations": [],  # Memory system removed
    }
