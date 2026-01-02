"""Context helpers service - Pattern and observation filtering for task execution.

Provides functions to select relevant patterns and observations
based on the files a task affects.

Note: Rule files were consolidated into CLAUDE.md (2026-01-02).
"""

from __future__ import annotations

from typing import Any

from ..storage import memory as memory_storage


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

    Searches for patterns that mention any of the affected files
    in their pattern text.

    Args:
        project_id: Project ID
        files: List of affected file paths
        min_confidence: Minimum confidence score for patterns

    Returns:
        List of pattern dicts with id, pattern, rationale, confidence
    """
    # Get all approved patterns for the project
    patterns = memory_storage.list_patterns(
        project_id=project_id,
        status="approved",
        limit=100,
    )

    # Filter to patterns that mention any of the affected files
    # and meet confidence threshold
    relevant_patterns: list[dict[str, Any]] = []

    for pattern in patterns:
        # Skip patterns below confidence threshold
        confidence = pattern.get("confidence", 0) or 0
        if confidence < min_confidence:
            continue

        pattern_text = pattern.get("pattern", "").lower()
        rationale = pattern.get("rationale", "").lower()

        # Check if any file path or module name is mentioned
        for file_path in files:
            # Extract module/file names for matching
            parts = file_path.replace("/", " ").replace(".", " ").split()
            if any(part.lower() in pattern_text or part.lower() in rationale for part in parts):
                relevant_patterns.append(
                    {
                        "id": pattern["id"],
                        "pattern": pattern.get("pattern"),
                        "rationale": pattern.get("rationale"),
                        "confidence": confidence,
                    }
                )
                break

    return relevant_patterns


def get_observations_for_files(
    project_id: str,
    files: list[str],
    types: list[str] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Get recent observations relevant to the given files.

    Searches for observations that mention any of the affected files.

    Args:
        project_id: Project ID
        files: List of affected file paths
        types: Optional list of observation types to filter (e.g., ['error', 'decision'])
        limit: Maximum observations to return

    Returns:
        List of observation dicts with id, title, narrative, observation_type
    """
    if types is None:
        types = ["error", "decision"]

    relevant_observations: list[dict[str, Any]] = []

    for obs_type in types:
        # Query recent observations of this type
        observations = memory_storage.query_observations(
            project_id=project_id,
            observation_type=obs_type,
            min_confidence=0.5,
            days=14,
            limit=50,
        )

        for obs in observations:
            # Check if any affected file is mentioned
            obs_files = obs.get("files") or []
            narrative = obs.get("narrative", "").lower()

            for file_path in files:
                # Check direct file match or narrative mention
                file_mentioned = any(file_path in obs_file for obs_file in obs_files)
                path_in_narrative = file_path.lower() in narrative

                if file_mentioned or path_in_narrative:
                    relevant_observations.append(
                        {
                            "id": obs["id"],
                            "title": obs.get("title"),
                            "narrative": obs.get("narrative"),
                            "observation_type": obs_type,
                            "confidence": obs.get("confidence"),
                        }
                    )
                    break

            if len(relevant_observations) >= limit:
                break

        if len(relevant_observations) >= limit:
            break

    return relevant_observations[:limit]
