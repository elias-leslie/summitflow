"""Validation helpers for done command.

Handles subtask ID parsing and error message processing.
"""

from __future__ import annotations

from typing import cast

# Error messages returned to the user when DB triggers block completion.
_ERR_DEPENDENCIES = (
    "Cannot complete: Blocking dependencies incomplete. Complete them first."
)
_ERR_QA_PENDING = "Cannot complete: QA status pending. Run: st qa pass <task-id>"
_ERR_SUBTASKS_INCOMPLETE = (
    "Cannot complete task: Some subtasks incomplete. Run: st subtask list <task-id>"
)


def is_subtask_id(id_str: str) -> bool:
    """Check if the ID looks like a subtask (e.g., 1.1, 2.3)."""
    if "." not in id_str:
        return False
    parts = id_str.split(".")
    if len(parts) != 2:
        return False
    return parts[0].isdigit() and parts[1].isdigit()


def _extract_detail_text(detail: str | dict[str, str] | object) -> str:
    """Extract a lowercased detail string from a str, dict, or unknown type."""
    if isinstance(detail, str):
        return detail.lower()
    if isinstance(detail, dict):
        return str(cast(dict[str, object], detail).get("detail", "")).lower()
    return ""


def parse_db_error(detail: str | dict[str, str] | object) -> str | None:
    """Parse DB trigger error messages into helpful guidance."""
    if not isinstance(detail, (str, dict)):
        return None

    msg = _extract_detail_text(detail)

    if "dependencies" in msg or "depends on" in msg:
        return _ERR_DEPENDENCIES

    if "qa" in msg and ("pending" in msg or "signoff" in msg):
        return _ERR_QA_PENDING

    if "subtask" in msg and ("incomplete" in msg or "not all" in msg):
        return _ERR_SUBTASKS_INCOMPLETE

    return None
