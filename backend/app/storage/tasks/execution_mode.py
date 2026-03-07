"""Shared task execution-mode rules."""

from __future__ import annotations

from typing import Any, Literal, cast

ExecutionMode = Literal["manual", "autonomous", "manual_only"]

EXECUTION_MODE_MANUAL: ExecutionMode = "manual"
EXECUTION_MODE_AUTONOMOUS: ExecutionMode = "autonomous"
EXECUTION_MODE_MANUAL_ONLY: ExecutionMode = "manual_only"
EXECUTION_MODE_VALUES = (
    EXECUTION_MODE_MANUAL,
    EXECUTION_MODE_AUTONOMOUS,
    EXECUTION_MODE_MANUAL_ONLY,
)

_AUTONOMOUS_TYPES = {"refactor", "debt", "regression"}


def resolve_execution_mode(
    *,
    execution_mode: str | None,
    autonomous: bool | None,
    task_type: str,
) -> ExecutionMode:
    """Resolve a task's authoritative execution mode."""
    if execution_mode in EXECUTION_MODE_VALUES:
        return cast(ExecutionMode, execution_mode)
    if autonomous:
        return EXECUTION_MODE_AUTONOMOUS
    if task_type in _AUTONOMOUS_TYPES:
        return EXECUTION_MODE_AUTONOMOUS
    return EXECUTION_MODE_MANUAL


def is_autonomous_mode(execution_mode: str | None) -> bool:
    """Return whether the mode allows autonomous pickup and execution."""
    return execution_mode == EXECUTION_MODE_AUTONOMOUS


def is_manual_only_mode(execution_mode: str | None) -> bool:
    """Return whether the mode blocks autonomous execution entirely."""
    return execution_mode == EXECUTION_MODE_MANUAL_ONLY


def normalize_execution_fields(
    *,
    task_type: str,
    execution_mode: str | None,
    autonomous: bool | None,
) -> dict[str, Any]:
    """Return normalized execution_mode/autonomous fields."""
    normalized_mode = resolve_execution_mode(
        execution_mode=execution_mode,
        autonomous=autonomous,
        task_type=task_type,
    )
    return {
        "execution_mode": normalized_mode,
        "autonomous": is_autonomous_mode(normalized_mode),
    }
