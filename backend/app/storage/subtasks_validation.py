"""Subtask validation - gate logic for completion criteria.

This module handles validation rules for marking subtasks as complete,
including step completion checks and citation acknowledgment gates.
"""

from __future__ import annotations

from typing import Any

from ..logging_config import get_logger

logger = get_logger(__name__)


class SubtaskGateError(Exception):
    """Raised when subtask completion gate is violated."""

    def __init__(self, message: str, incomplete_steps: list[int] | None = None):
        super().__init__(message)
        self.incomplete_steps = incomplete_steps or []


def _classify_plan_defect(
    step: dict[str, Any],
    step_passes_lookup: dict[int, bool],
) -> str:
    """Classify a plan_defect step as 'valid' or 'invalid'.

    Returns 'valid' if the fix step exists and is passing, 'invalid' otherwise.
    """
    fix_step_num = step.get("fix_step_number")
    if fix_step_num and step_passes_lookup.get(fix_step_num):
        return "valid"
    return "invalid"


def _classify_steps(
    steps: list[dict[str, Any]],
    step_passes_lookup: dict[int, bool],
    plan_defect_status: str,
) -> tuple[list[int], list[int], list[tuple[int, Any]]]:
    """Classify steps into incomplete, valid plan_defects, and invalid plan_defects.

    Returns:
        Tuple of (incomplete, plan_defects, invalid_plan_defects).
    """
    incomplete: list[int] = []
    plan_defects: list[int] = []
    invalid_plan_defects: list[tuple[int, Any]] = []

    for s in steps:
        if s.get("passes"):
            continue
        if s.get("status") != plan_defect_status:
            incomplete.append(s["step_number"])
            continue
        kind = _classify_plan_defect(s, step_passes_lookup)
        if kind == "valid":
            plan_defects.append(s["step_number"])
        else:
            fix_step_num = s.get("fix_step_number")
            invalid_plan_defects.append((s["step_number"], fix_step_num))
            incomplete.append(s["step_number"])

    return incomplete, plan_defects, invalid_plan_defects


def _build_incomplete_error(
    subtask_id: str,
    incomplete: list[int],
    plan_defects: list[int],
    invalid_plan_defects: list[tuple[int, Any]],
) -> str:
    """Build the error message for incomplete steps."""
    msg = (
        f"Cannot pass subtask {subtask_id}: steps {incomplete} are not complete. "
        "Each step must pass before the subtask can be marked complete."
    )
    if invalid_plan_defects:
        bad_steps = [s for s, _ in invalid_plan_defects]
        msg += (
            f" Steps {bad_steps} are marked plan_defect "
            "but their fix steps are not passing."
        )
    if plan_defects:
        msg += f" (Plan defect steps {plan_defects} are allowed to be skipped.)"
    return msg


def validate_steps_complete(subtask_id: str, steps: list[dict[str, Any]]) -> None:
    """Validate that all steps are complete before marking subtask as passed.

    Args:
        subtask_id: Subtask ID for error messages (e.g., "1.1")
        steps: List of step dictionaries from get_steps_for_subtask

    Raises:
        SubtaskGateError: If any steps are incomplete or validation fails
    """
    from .steps import STEP_STATUS_PLAN_DEFECT

    if not steps:
        return

    step_passes_lookup = {s["step_number"]: s.get("passes", False) for s in steps}
    incomplete, plan_defects, invalid_plan_defects = _classify_steps(
        steps, step_passes_lookup, STEP_STATUS_PLAN_DEFECT
    )

    if incomplete:
        msg = _build_incomplete_error(
            subtask_id, incomplete, plan_defects, invalid_plan_defects
        )
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
