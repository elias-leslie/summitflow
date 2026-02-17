"""Debug logging module that emits to the event system with visibility=debug.

Events emitted here are only visible when using `st exec-monitor --debug`.
Zero overhead when DEBUG is not set - all functions early-return before doing work.

Environment variables:
    DEBUG: Set to "true" to enable debug event emission
    DEBUG_LEVEL: 1=basic flow, 2=detailed with timing, 3=verbose with payloads

Usage:
    from app.core.debug import debug, debug_section, debug_async_timer

    # Basic debug message
    debug("Processing subtask", subtask_id="1.1")

    # Section markers for phase separation
    debug_section("Verification", task_id="task-123")

    # Timing decorator for async functions
    @debug_async_timer
    async def my_function():
        ...
"""

from __future__ import annotations

from typing import Any

from .debug_decorators import (
    debug_async_timer,
    debug_async_timer_decorator,
    debug_timer,
    debug_timer_decorator,
)
from .debug_messages import debug_error, debug_success, debug_warning
from .debug_utils import (
    emit_debug_event,
    emit_stderr,
    format_attributes,
    get_caller_info,
    is_debug_enabled,
)

__all__ = [
    "debug",
    "debug_async_timer",
    "debug_async_timer_decorator",
    "debug_error",
    "debug_section",
    "debug_success",
    "debug_timer",
    "debug_timer_decorator",
    "debug_warning",
    "is_debug_enabled",
]


def debug(
    message: str,
    *,
    task_id: str | None = None,
    project_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Emit a basic debug message (level 1).

    Args:
        message: Debug message to emit
        task_id: Task ID for event routing
        project_id: Project ID for persistence
        **kwargs: Additional attributes to include
    """
    if not is_debug_enabled(1):
        return

    func_name, _, _ = get_caller_info()
    attrs = format_attributes(function_name=func_name, **kwargs)
    emit_stderr(message, function_name=func_name, **kwargs)
    emit_debug_event(
        message,
        task_id=task_id,
        project_id=project_id,
        **attrs,
    )


def debug_section(
    section_name: str,
    *,
    task_id: str | None = None,
    project_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Emit a section marker for phase separation (level 1).

    Use to mark major phases like "Verification", "Agent Execution", etc.
    """
    if not is_debug_enabled(1):
        return

    attrs = format_attributes(section=section_name, **kwargs)
    marker = f"═══ {section_name.upper()} ═══"
    emit_stderr(marker)
    emit_debug_event(
        marker,
        source="section",
        task_id=task_id,
        project_id=project_id,
        **attrs,
    )
