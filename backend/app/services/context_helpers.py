"""Context helpers service - Rule and pattern filtering for task execution.

Provides functions to select relevant rules, patterns, and observations
based on the files a task affects.
"""

from __future__ import annotations

from typing import Any

from ..storage import memory as memory_storage

# Map file path patterns to relevant rule files
# Key: path pattern (prefix match), Value: list of rule filenames
RULE_FILE_MAPPING: dict[str, list[str]] = {
    "backend/": [
        "architecture-coherence.md",
        "code-cleanliness.md",
    ],
    "backend/app/api/": [
        "architecture-coherence.md",
        "code-cleanliness.md",
    ],
    "backend/app/storage/": [
        "architecture-coherence.md",
        "code-cleanliness.md",
    ],
    "backend/app/services/explorer/": [
        "explorer-architecture.md",
        "architecture-coherence.md",
        "code-cleanliness.md",
    ],
    "frontend/": [
        "ui-backend-lockstep.md",
        "code-cleanliness.md",
    ],
    "frontend/components/explorer/": [
        "explorer-architecture.md",
        "ui-backend-lockstep.md",
        "code-cleanliness.md",
    ],
}


def filter_rules_by_files(files: list[str]) -> list[str]:
    """Filter rule files based on affected file paths.

    Returns the unique set of rule files relevant to the given file paths.

    Args:
        files: List of file paths affected by a task

    Returns:
        List of unique rule filenames (e.g., ['architecture-coherence.md', 'code-cleanliness.md'])
    """
    rules: set[str] = set()

    for file_path in files:
        # Match against rule mappings (longest prefix first for specificity)
        matched_patterns = [
            pattern for pattern in RULE_FILE_MAPPING if file_path.startswith(pattern)
        ]

        if matched_patterns:
            # Use the most specific match (longest prefix)
            best_match = max(matched_patterns, key=len)
            rules.update(RULE_FILE_MAPPING[best_match])
        else:
            # Default rules for any file
            rules.add("architecture-coherence.md")
            rules.add("code-cleanliness.md")

    return sorted(rules)


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
