"""Basic CRUD operations for steps.

This module provides the public API for step CRUD operations by delegating
to focused submodules for validation, serialization, and query execution.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

# Import query execution functions
from .steps_crud_queries import (
    execute_append_steps,
    execute_bulk_insert,
    execute_create_step,
    execute_delete_all_steps,
    execute_get_single_step,
    execute_get_steps,
    execute_insert_step,
)

# Re-export for backward compatibility (used by tests and other modules)
from .steps_crud_serialization import (
    EXPECTED_STEP_COLUMNS,
    STEP_COLUMNS,
)
from .steps_crud_serialization import (
    row_to_dict as _row_to_dict,
)
from .steps_crud_validation import sanitize_verify_command as _sanitize_verify_command

__all__ = [
    "EXPECTED_STEP_COLUMNS",
    "STEP_COLUMNS",
    "_row_to_dict",
    "_sanitize_verify_command",
    "append_steps",
    "bulk_create_steps",
    "create_step",
    "delete_steps_for_subtask",
    "get_step",
    "get_steps_for_subtask",
    "insert_step",
]


def create_step(
    subtask_id: str,
    step_number: int,
    description: str,
    spec: dict[str, Any] | None = None,
    verify_command: str | None = None,
    expected_output: str | None = None,
) -> dict[str, Any]:
    """Create a new step for a subtask.

    Args:
        subtask_id: Parent subtask ID (e.g., "task-abc123-1.1")
        step_number: 1-indexed step number within subtask
        description: Step description text
        spec: Optional JSONB spec for implementation details
        verify_command: Bash command to verify step completion
        expected_output: Expected output pattern for verification

    Returns:
        The created step dict.

    Raises:
        Exception: If subtask_id doesn't exist (FK constraint violation)
    """
    return execute_create_step(
        subtask_id, step_number, description, spec, verify_command, expected_output
    )


def get_steps_for_subtask(subtask_id: str) -> list[dict[str, Any]]:
    """Get all steps for a subtask, ordered by step_number.

    Args:
        subtask_id: Parent subtask ID

    Returns:
        List of step dicts, ordered by step_number.
    """
    return execute_get_steps(subtask_id)


def get_step(subtask_id: str, step_number: int) -> dict[str, Any] | None:
    """Get a single step by subtask_id and step_number.

    Args:
        subtask_id: Parent subtask ID
        step_number: Step number (1-indexed)

    Returns:
        Step dict or None if not found.
    """
    return execute_get_single_step(subtask_id, step_number)


def bulk_create_steps(
    subtask_id: str,
    steps: Sequence[str | dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create multiple steps for a subtask in a single transaction.

    Steps are automatically numbered starting from 1.

    Args:
        subtask_id: Parent subtask ID
        steps: List of step items - either strings (description only)
               or dicts with {description, spec, verify_command, expected_output}

    Returns:
        List of created step dicts.

    Raises:
        Exception: If subtask_id doesn't exist or on DB error.
    """
    return execute_bulk_insert(subtask_id, steps)


def append_steps(
    subtask_id: str,
    steps: Sequence[str | dict[str, Any]],
) -> list[dict[str, Any]]:
    """Append steps to a subtask, continuing from the highest existing step number.

    Unlike bulk_create_steps which starts at 1, this finds the max step_number
    and continues from there.

    Args:
        subtask_id: Parent subtask ID
        steps: List of step items - either strings (description only)
               or dicts with {description, spec, verify_command, expected_output}

    Returns:
        List of created step dicts.

    Raises:
        Exception: If subtask_id doesn't exist or on DB error.
    """
    return execute_append_steps(subtask_id, steps)


def delete_steps_for_subtask(subtask_id: str) -> int:
    """Delete all steps for a subtask.

    Args:
        subtask_id: Parent subtask ID

    Returns:
        Number of steps deleted.
    """
    return execute_delete_all_steps(subtask_id)


def insert_step(
    subtask_id: str,
    position: int,
    description: str,
    spec: dict[str, Any] | None = None,
    verify_command: str | None = None,
    expected_output: str | None = None,
) -> dict[str, Any]:
    """Insert a step at a specific position, shifting existing steps down.

    This allows inserting a step before an existing step. All steps at or after
    the insertion position are renumbered (incremented by 1).

    Args:
        subtask_id: Parent subtask ID (e.g., "task-abc123-1.1")
        position: Position to insert at (1-indexed). Existing steps at this
                  position and after are shifted down.
        description: Step description text
        spec: Optional JSONB spec for implementation details
        verify_command: Bash command to verify step completion
        expected_output: Expected output pattern for verification

    Returns:
        The created step dict.

    Raises:
        ValueError: If position < 1
        Exception: If subtask_id doesn't exist (FK constraint violation)
    """
    return execute_insert_step(
        subtask_id, position, description, spec, verify_command, expected_output
    )
