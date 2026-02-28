"""Read-only handler implementations for step operations.

This module contains handlers for querying step data.
"""

from __future__ import annotations

from ...schemas.steps import StepResponse, StepSummary


def get_steps_handler(table_id: str) -> list[StepResponse]:
    """Get all steps for a subtask.

    Args:
        table_id: Subtask table ID

    Returns:
        List of steps as StepResponse objects
    """
    from ...storage.steps import get_steps_for_subtask

    steps = get_steps_for_subtask(table_id)
    return [StepResponse(**s) for s in steps]


def get_summary_handler(table_id: str) -> StepSummary:
    """Get step summary for a subtask.

    Args:
        table_id: Subtask table ID

    Returns:
        Step summary
    """
    from ...storage.steps import get_step_summary

    summary = get_step_summary(table_id)
    return StepSummary(**summary)
