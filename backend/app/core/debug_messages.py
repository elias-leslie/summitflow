"""Specialized debug message functions.

Provides pre-configured debug functions for common message types
like success, error, and warning messages.
"""

from __future__ import annotations

from typing import Any

from .debug_utils import (
    emit_debug_event,
    emit_stderr,
    format_attributes,
    get_caller_info,
    is_debug_enabled,
)


def debug_success(
    message: str,
    *,
    task_id: str | None = None,
    project_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Emit a success debug message (level 1)."""
    if not is_debug_enabled(1):
        return

    func_name, _, _ = get_caller_info()
    attrs = format_attributes(function_name=func_name, status="success", **kwargs)
    emit_stderr(f"✓ {message}", function_name=func_name, **kwargs)
    emit_debug_event(
        f"✓ {message}",
        task_id=task_id,
        project_id=project_id,
        **attrs,
    )


def debug_error(
    message: str,
    *,
    task_id: str | None = None,
    project_id: str | None = None,
    error: str | Exception | None = None,
    **kwargs: Any,
) -> None:
    """Emit an error debug message (level 1)."""
    if not is_debug_enabled(1):
        return

    func_name, _, _ = get_caller_info()
    error_str = str(error) if error else None
    attrs = format_attributes(function_name=func_name, status="error", error=error_str, **kwargs)
    emit_stderr(f"✗ {message}", function_name=func_name, error=error_str, **kwargs)
    emit_debug_event(
        f"✗ {message}",
        level="error",
        task_id=task_id,
        project_id=project_id,
        **attrs,
    )


def debug_warning(
    message: str,
    *,
    task_id: str | None = None,
    project_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Emit a warning debug message (level 1)."""
    if not is_debug_enabled(1):
        return

    func_name, _, _ = get_caller_info()
    attrs = format_attributes(function_name=func_name, status="warning", **kwargs)
    emit_stderr(f"⚠ {message}", function_name=func_name, **kwargs)
    emit_debug_event(
        f"⚠ {message}",
        level="warning",
        task_id=task_id,
        project_id=project_id,
        **attrs,
    )
