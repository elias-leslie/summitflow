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
