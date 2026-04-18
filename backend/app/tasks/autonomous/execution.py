"""Subtask execution task using Agent Hub complete() with agentic mode.

Executes subtasks with fresh context per subtask to prevent context rot.
Uses complete() with execute_tools=True for agentic execution.

This module is now a thin wrapper around the refactored execution package.
All logic has been moved to focused modules in exec_modules/ subdirectory.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# Re-export commonly used exceptions and utilities for backward compatibility
from .exec_modules.agent_routing import (
    detect_progress as _detect_progress,
)
from .exec_modules.agent_routing import (
    request_extension as _request_extension,
)
from .exec_modules.agent_routing import (
    supervisor_circuit_breaker_triage as _supervisor_circuit_breaker_triage,
)
from .exec_modules.checkout import (
    check_checkout_health as _check_checkout_health,
)
from .exec_modules.checkout import (
    check_main_repo_leakage as _check_main_repo_leakage,
)
from .exec_modules.quality import (
    PristineCheckError,
    check_pristine_codebase,
    pristine_self_heal,
)
from .exec_modules.quality import (
    parse_error_count as _parse_error_count,
)
from .exec_modules.subtask_executor import execute_subtask as _execute_subtask

_INFRASTRUCTURE_PATTERNS = [
    "command not found",
    "No such file or directory",
    "Permission denied",
    "not recognized as",
    "cannot execute binary",
    "is not installed",
    "ModuleNotFoundError",
    "ImportError: cannot import",
    "ImportError while loading",
    "FileNotFoundError",
    "timed out",
    "Connection refused",
]


def _is_infrastructure_failure(output: str, reason: str, returncode: int) -> bool:
    """Classify whether a failure is infrastructure (plan defect) vs code."""
    combined = f"{output}\n{reason}".lower()
    return any(pat.lower() in combined for pat in _INFRASTRUCTURE_PATTERNS)


__all__ = [
    "PristineCheckError",
    "_check_checkout_health",
    "_check_main_repo_leakage",
    "_detect_progress",
    "_execute_subtask",
    "_is_infrastructure_failure",
    "_parse_error_count",
    "_request_extension",
    "_supervisor_circuit_breaker_triage",
    "check_pristine_codebase",
    "pristine_self_heal",
    "start_execution",
]


def start_execution(
    task_id: str,
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    """Start autonomous execution of a task.

    Executes subtasks in order with fresh context per subtask.
    Uses complete() with execute_tools=True for agentic execution.

    Concurrency is handled by Hatchet ConcurrencyExpression (max_runs=1 per task_id).

    Args:
        task_id: The task ID to execute
        project_id: The project ID
        dispatch: Optional callback to trigger downstream workflows

    Returns:
        Execution result with status
    """
    from .exec_modules.orchestrator import start_execution as _start_execution

    return _start_execution(task_id, project_id, dispatch=dispatch)


# Backward compatibility aliases (if needed by other modules)
def _execute_task_locked(
    task_id: str,
    project_id: str,
    dispatch: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    """Backward compatibility wrapper for execute_task_locked."""
    from .exec_modules.orchestrator import execute_task_locked

    return execute_task_locked(task_id, project_id, dispatch=dispatch)
