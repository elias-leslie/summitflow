"""Model selection logic for task execution.

Separated from loop.py to reduce file size.
"""

from __future__ import annotations

from typing import Any

from .agent import consult_alternate


def select_model(
    iteration: int,
    consecutive_identical_errors: int,
    primary_model: dict[str, Any],
    alternate_model: dict[str, Any],
    current_task: dict[str, Any],
    iteration_context: dict[str, Any] | None,
    was_consulted: bool,
    was_handoff: bool,
) -> tuple[dict[str, Any], bool, bool, dict[str, Any] | None]:
    """Select model based on thrashing detection."""
    if consecutive_identical_errors >= 2 and iteration >= 3:
        if iteration == 5:
            was_handoff = True
            if iteration_context:
                iteration_context["handoff_context"] = (
                    f"Failed after {iteration - 1} attempts with errors:\n"
                    f"{iteration_context.get('test_failures', '')}"
                )
            return alternate_model, was_consulted, was_handoff, iteration_context
        else:
            was_consulted = True
            advice = consult_alternate(
                alternate_model,
                current_task,
                iteration_context.get("test_failures", "") if iteration_context else "",
            )
            if iteration_context:
                iteration_context["advice"] = advice
            return primary_model, was_consulted, was_handoff, iteration_context

    return primary_model, was_consulted, was_handoff, iteration_context
