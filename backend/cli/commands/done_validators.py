"""Validation helpers for done command.

Handles subtask ID parsing and error message processing.
"""

from __future__ import annotations


def is_subtask_id(id_str: str) -> bool:
    """Check if the ID looks like a subtask (e.g., 1.1, 2.3)."""
    if "." not in id_str:
        return False

    parts = id_str.split(".")
    if len(parts) != 2:
        return False

    return parts[0].isdigit() and parts[1].isdigit()


def parse_db_error(detail: str | dict[str, str] | object) -> str | None:
    """Parse DB trigger error messages into helpful guidance."""
    if not isinstance(detail, (str, dict)):
        return None

    msg = (
        str(detail).lower()
        if isinstance(detail, str)
        else str(detail.get("detail", "")).lower() if isinstance(detail, dict) else ""
    )

    if "zero steps" in msg or ("steps" in msg and "zero" in msg):
        return "Cannot complete: Task has no steps. Create subtasks with steps first."

    if "steps" in msg and ("incomplete" in msg or "not verified" in msg):
        return "Cannot complete: Some steps not verified. Run: st step pass <subtask> <step>"

    if "dependencies" in msg or "depends on" in msg:
        return "Cannot complete: Blocking dependencies incomplete. Complete them first."

    if "qa" in msg and ("pending" in msg or "signoff" in msg):
        return "Cannot complete: QA status pending. Run: st qa pass <task-id>"

    if "subtask" in msg and ("incomplete" in msg or "not all" in msg):
        return "Cannot complete task: Some subtasks incomplete. Run: st subtask list <task-id>"

    return None
