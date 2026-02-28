"""Subtask validation - gate logic for completion criteria.

This module handles validation rules for marking subtasks as complete,
including step completion checks and citation acknowledgment gates.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SubtaskGateError(Exception):
    """Raised when subtask completion gate is violated."""

    def __init__(self, message: str, incomplete_steps: list[int] | None = None):
        super().__init__(message)
        self.incomplete_steps = incomplete_steps or []


def validate_steps_complete(subtask_id: str, steps: list[dict[str, Any]]) -> None:
    """Validate that all steps are complete before marking subtask as passed.

    Args:
        subtask_id: Subtask ID for error messages (e.g., "1.1")
        steps: List of step dictionaries from get_steps_for_subtask

    Raises:
        SubtaskGateError: If any steps are incomplete or validation fails
    """
    from .steps import STEP_STATUS_PLAN_DEFECT

    # Gate: Subtask must have at least one step to be marked as passed
    if not steps:
        return

    # Build a lookup for step passes status
    step_passes_lookup = {s["step_number"]: s.get("passes", False) for s in steps}

    incomplete = []
    plan_defects = []
    invalid_plan_defects = []

    for s in steps:
        if not s.get("passes"):
            if s.get("status") == STEP_STATUS_PLAN_DEFECT:
                # Validate the fix_step is still passing
                fix_step_num = s.get("fix_step_number")
                if fix_step_num and step_passes_lookup.get(fix_step_num):
                    # Fix step exists and is passing - allow plan_defect to be skipped
                    plan_defects.append(s["step_number"])
                else:
                    # Fix step missing or not passing - treat as incomplete
                    invalid_plan_defects.append((s["step_number"], fix_step_num))
                    incomplete.append(s["step_number"])
            else:
                incomplete.append(s["step_number"])

    if incomplete:
        msg = (
            f"Cannot pass subtask {subtask_id}: steps {incomplete} are not complete. "
            "Each step must pass before the subtask can be marked complete."
        )
        if invalid_plan_defects:
            msg += (
                f" Steps {[s for s, _ in invalid_plan_defects]} are marked plan_defect "
                "but their fix steps are not passing."
            )
        if plan_defects:
            msg += f" (Plan defect steps {plan_defects} are allowed to be skipped.)"
        raise SubtaskGateError(msg, incomplete_steps=incomplete)

    if plan_defects:
        logger.info(
            "Subtask %s passing with plan_defect steps: %s",
            subtask_id,
            plan_defects,
        )


def validate_citations_acknowledged(
    subtask_table_id: str, subtask_id: str, acknowledged_at: Any
) -> None:
    """Validate that memory citations have been acknowledged.

    Args:
        subtask_table_id: Full table ID for database lookup
        subtask_id: Short subtask ID for error messages (e.g., "1.1")
        acknowledged_at: citations_acknowledged_at timestamp from database

    Raises:
        SubtaskGateError: If citations have not been acknowledged
    """
    if acknowledged_at is None:
        raise SubtaskGateError(
            f"Before completing subtask {subtask_id}, please reflect: "
            "Did any memories help? Use 'st subtask citations M:xxx+' to cite them, "
            "or 'st subtask citations --none' to confirm none were needed.",
            incomplete_steps=[],
        )
