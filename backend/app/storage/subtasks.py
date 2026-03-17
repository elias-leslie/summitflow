"""Subtasks storage layer - CRUD operations for task implementation subtasks.

This module provides data access for the task_subtasks table, which stores
normalized subtask data for structured task execution tracking.
"""

from __future__ import annotations

from typing import Any

from ..logging_config import get_logger
from .subtasks_crud import generate_subtask_id as _generate_subtask_id
from .tasks import canonicalize_task_id

logger = get_logger(__name__)


# =============================================================================
# CRUD Operations (delegates to subtasks_crud module)
# =============================================================================


def create_subtask(
    task_id: str,
    subtask_id: str,
    description: str,
    display_order: int,
    phase: str | None = None,
    steps: list[str | dict[str, Any]] | None = None,
    subtask_type: str | None = None,
) -> dict[str, Any]:
    """Create a new subtask."""
    from .subtasks_create import create_subtask as _create

    return _create(
        canonicalize_task_id(task_id),
        subtask_id,
        description,
        display_order,
        phase,
        steps,
        subtask_type,
    )


def get_subtask(task_id: str, subtask_id: str) -> dict[str, Any] | None:
    """Get a single subtask by task_id and subtask_id."""
    from .subtasks_crud import get_subtask as _get

    return _get(canonicalize_task_id(task_id), subtask_id)


def get_subtask_by_table_id(table_id: str) -> dict[str, Any] | None:
    """Get a single subtask by its full table ID."""
    from .subtasks_crud import get_subtask_by_table_id as _get

    return _get(table_id)


def get_subtasks_for_task(
    task_id: str,
    include_steps: bool = False,
) -> list[dict[str, Any]]:
    """Get all subtasks for a task, ordered by display_order."""
    from .subtasks_crud import get_subtasks_for_task as _get

    return _get(canonicalize_task_id(task_id), include_steps)


def update_subtask_passes(
    task_id: str,
    subtask_id: str,
    passes: bool,
) -> dict[str, Any] | None:
    """Update subtask passes status with validation gates."""
    from .subtasks_passes import update_subtask_passes as _update

    return _update(canonicalize_task_id(task_id), subtask_id, passes)


def delete_subtasks_for_task(task_id: str) -> int:
    """Delete all subtasks for a task."""
    from .subtasks_deletion import delete_subtasks_for_task as _delete

    return _delete(canonicalize_task_id(task_id))


def delete_subtask(task_id: str, subtask_id: str) -> bool:
    """Delete a single subtask and its steps."""
    from .subtasks_deletion import delete_subtask as _delete

    return _delete(canonicalize_task_id(task_id), subtask_id)


def bulk_create_subtasks(
    task_id: str,
    subtasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create multiple subtasks for a task in a single transaction."""
    from .subtasks_bulk import bulk_create_subtasks as _bulk_create

    return _bulk_create(canonicalize_task_id(task_id), subtasks)


def get_subtask_summary(task_id: str) -> dict[str, Any]:
    """Get summary of subtask completion for a task."""
    from .subtasks_summaries import get_subtask_summary as _get_summary

    return _get_summary(canonicalize_task_id(task_id))


# =============================================================================
# Dependency handling (delegates to subtask_dependencies module)
# =============================================================================


def add_subtask_dependency(
    task_id: str, subtask_id: str, depends_on_subtask_id: str
) -> dict[str, Any] | None:
    """Add a dependency between two subtasks."""
    from .subtask_dependencies import add_dependency

    canonical_task_id = canonicalize_task_id(task_id)
    table_id = _generate_subtask_id(canonical_task_id, subtask_id)
    depends_on_table_id = _generate_subtask_id(canonical_task_id, depends_on_subtask_id)
    return add_dependency(table_id, depends_on_table_id)


def get_subtask_dependencies(task_id: str, subtask_id: str) -> list[str]:
    """Get all subtasks that this subtask depends on."""
    from .subtask_dependencies import get_dependencies

    table_id = _generate_subtask_id(canonicalize_task_id(task_id), subtask_id)
    dep_table_ids = get_dependencies(table_id)
    return [tid.split("-")[-1] for tid in dep_table_ids]


def bulk_add_subtask_dependencies(
    task_id: str, dependencies: list[tuple[str, str]]
) -> list[dict[str, Any]]:
    """Add multiple dependencies at once."""
    from .subtask_dependencies import bulk_add_dependencies

    table_id_deps = [
        (_generate_subtask_id(canonicalize_task_id(task_id), s), _generate_subtask_id(canonicalize_task_id(task_id), d))
        for s, d in dependencies
    ]
    return bulk_add_dependencies(table_id_deps)


# =============================================================================
# Subtask Summaries (delegates to subtasks_summaries module)
# =============================================================================


def insert_subtask_summary(
    subtask_id: str,
    summary: str,
    files_modified: list[str] | None = None,
    decisions_made: list[str] | None = None,
) -> dict[str, Any]:
    """Insert or update a handoff summary for a subtask."""
    from .subtasks_summaries import insert_subtask_summary as _insert

    return _insert(subtask_id, summary, files_modified, decisions_made)


def get_previous_summary(subtask_id: str) -> dict[str, Any] | None:
    """Get the summary for a specific subtask."""
    from .subtasks_summaries import get_previous_summary as _get

    return _get(subtask_id)


def get_handoff_context(task_id: str, current_subtask_id: str) -> dict[str, Any]:
    """Build handoff context for a subtask from all previous completed subtasks."""
    from .subtasks_summaries import get_handoff_context as _get_context

    return _get_context(canonicalize_task_id(task_id), current_subtask_id)


# =============================================================================
# Citation handling (delegates to subtasks_citations module)
# =============================================================================


def log_citations(
    task_id: str, subtask_id: str, citations: list[str], client: Any | None = None
) -> int:
    """Log episode citations for a subtask with ratings."""
    from .subtasks_citations import log_citations as _log_citations

    table_id = _generate_subtask_id(canonicalize_task_id(task_id), subtask_id)
    return _log_citations(table_id, citations, client)


def acknowledge_no_citations(task_id: str, subtask_id: str) -> bool:
    """Acknowledge that no memories were needed for this subtask."""
    from .subtasks_citations import acknowledge_no_citations as _acknowledge

    table_id = _generate_subtask_id(canonicalize_task_id(task_id), subtask_id)
    return _acknowledge(table_id)
