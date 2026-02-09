"""Common field definitions for agent sessions."""

from __future__ import annotations

from typing import Any

# Standard session fields (without build_state)
SESSION_FIELDS = """
    id, project_id, session_id, agent_type, status, started_at, ended_at,
    capabilities_attempted, capabilities_passed, capabilities_failed,
    tests_run, tests_passed, tests_failed, notes, git_commit_sha,
    created_at, updated_at
"""

# Session fields with build_state
SESSION_FIELDS_WITH_STATE = SESSION_FIELDS + ", build_state"


def row_to_dict(row: tuple[Any, ...] | None, include_build_state: bool = False) -> dict[str, Any]:
    """Convert database row to session dict.

    Args:
        row: Database row tuple
        include_build_state: Whether row includes build_state field

    Returns:
        Session dict or empty dict if row is None
    """
    if row is None:
        return {}

    result = {
        "id": row[0],
        "project_id": row[1],
        "session_id": row[2],
        "agent_type": row[3],
        "status": row[4],
        "started_at": row[5].isoformat() if row[5] else None,
        "ended_at": row[6].isoformat() if row[6] else None,
        "capabilities_attempted": list(row[7]) if row[7] else [],
        "capabilities_passed": list(row[8]) if row[8] else [],
        "capabilities_failed": list(row[9]) if row[9] else [],
        "tests_run": row[10],
        "tests_passed": row[11],
        "tests_failed": row[12],
        "notes": row[13],
        "git_commit_sha": row[14],
        "created_at": row[15].isoformat() if row[15] else None,
        "updated_at": row[16].isoformat() if row[16] else None,
    }

    if include_build_state and len(row) > 17:
        result["build_state"] = row[17] if row[17] else {}

    return result
