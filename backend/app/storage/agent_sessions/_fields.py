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


def _isoformat(value: Any) -> str | None:
    """Return isoformat string for a datetime value, or None."""
    return value.isoformat() if value else None


def _as_list(value: Any) -> list[Any]:
    """Return a list from a sequence value, or empty list."""
    return list(value) if value else []


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
        "started_at": _isoformat(row[5]),
        "ended_at": _isoformat(row[6]),
        "capabilities_attempted": _as_list(row[7]),
        "capabilities_passed": _as_list(row[8]),
        "capabilities_failed": _as_list(row[9]),
        "tests_run": row[10],
        "tests_passed": row[11],
        "tests_failed": row[12],
        "notes": row[13],
        "git_commit_sha": row[14],
        "created_at": _isoformat(row[15]),
        "updated_at": _isoformat(row[16]),
    }

    if include_build_state and len(row) > 17:
        result["build_state"] = row[17] if row[17] else {}

    return result
