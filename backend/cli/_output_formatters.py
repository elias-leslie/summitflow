"""Re-export facade for CLI output formatters.

All compact formatters live in _formatters_compact.
All context formatters live in _formatters_context.
This module preserves the original public API.
"""

from __future__ import annotations

from ._formatters_compact import (
    format_compact_dep,
    format_compact_step,
    format_compact_subtask,
    format_compact_task,
    truncate,
)
from ._formatters_context import (
    format_context_blockers,
    format_context_decisions,
    format_context_log,
    format_context_references,
    format_context_snapshot,
    format_context_subtasks,
    format_context_task,
    format_subtask_context_dependencies,
    format_subtask_context_subtask,
    format_subtask_context_task_summary,
)

__all__ = [
    "format_compact_dep",
    "format_compact_step",
    "format_compact_subtask",
    "format_compact_task",
    "format_context_blockers",
    "format_context_decisions",
    "format_context_log",
    "format_context_references",
    "format_context_snapshot",
    "format_context_subtasks",
    "format_context_task",
    "format_subtask_context_dependencies",
    "format_subtask_context_subtask",
    "format_subtask_context_task_summary",
    "truncate",
]
