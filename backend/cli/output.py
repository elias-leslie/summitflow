"""JSON output formatters for CLI.

All output functions emit JSON for AI agent consumption.
Default: compact JSON (single-line). Use --human for pretty-printed.
Use --compact for TOON-style one-liner per item.

This module re-exports all public symbols from focused sub-modules:
- _output_state: mode flags and setters/getters
- _output_core: JSON primitive, status messages, error handling
- _output_entities: task/subtask/step/dep/test output functions
- _output_context_views: full context and subtask-context output
"""

from __future__ import annotations

from ._output_context_views import output_context, output_subtask_context
from ._output_core import (
    handle_api_error,
    output_error,
    output_json,
    output_success,
    output_warning,
    require_explicit_project,
)
from ._output_entities import (
    output_blocked_tasks,
    output_deps,
    output_steps,
    output_subtasks,
    output_task,
    output_task_list,
    output_tests,
)
from ._output_state import (
    is_compact,
    is_progress_only,
    set_compact_output,
    set_human_output,
    set_progress_only,
)

__all__ = [
    "handle_api_error",
    "is_compact",
    "is_progress_only",
    "output_blocked_tasks",
    "output_context",
    "output_deps",
    "output_error",
    "output_json",
    "output_steps",
    "output_subtask_context",
    "output_subtasks",
    "output_success",
    "output_task",
    "output_task_list",
    "output_tests",
    "output_warning",
    "require_explicit_project",
    "set_compact_output",
    "set_human_output",
    "set_progress_only",
]
