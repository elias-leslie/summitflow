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

import functools
import json
import os
import sys
import time
from collections.abc import AsyncGenerator, Callable, Coroutine, Generator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from typing import Any

_DEBUG = os.environ.get("DEBUG", "").lower() == "true"
_DEBUG_LEVEL = int(os.environ.get("DEBUG_LEVEL", "1"))


def is_debug_enabled(level: int = 1) -> bool:
    """Check if debug logging is enabled for the given level."""
    return _DEBUG and level <= _DEBUG_LEVEL


def _get_caller_info() -> tuple[str, str, int]:
    """Get the calling function name, filename, and line number."""
    import inspect

    frame = inspect.currentframe()
    if frame is None:
        return "unknown", "unknown", 0
    try:
        caller = frame.f_back
        if caller is None or caller.f_back is None:
            return "unknown", "unknown", 0
        caller = caller.f_back
        return (
            caller.f_code.co_name,
            caller.f_code.co_filename.split("/")[-1],
            caller.f_lineno,
        )
    finally:
        del frame


def _format_attributes(
    elapsed_ms: float | None = None,
    function_name: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Format attributes for event emission."""
    attrs: dict[str, Any] = {}
    if elapsed_ms is not None:
        attrs["elapsed_ms"] = round(elapsed_ms, 2)
    if function_name is not None:
        attrs["function_name"] = function_name
    for key, value in kwargs.items():
        if value is not None:
            try:
                json.dumps(value)
                attrs[key] = value
            except (TypeError, ValueError):
                attrs[key] = str(value)
    return attrs


def _emit_debug_event(
    message: str,
    level: str = "debug",
    source: str = "debug",
    task_id: str | None = None,
    project_id: str | None = None,
    **attributes: Any,
) -> None:
    """Emit a debug event via the event system."""
    from ..services.pubsub import publish_ws_event

    if task_id is None:
        task_id = "debug"

    publish_ws_event(
        task_id,
        {
            "type": "debug",
            "task_id": task_id,
            "data": {"level": level, "message": message, "source": source, **attributes},
            "timestamp": datetime.now(UTC).isoformat(),
        },
        project_id=project_id,
        trace_id=task_id,
        source=source,
        level="debug",
        visibility="debug",
    )


def _emit_stderr(
    message: str,
    level: str = "debug",
    function_name: str | None = None,
    elapsed_ms: float | None = None,
    **attributes: Any,
) -> None:
    """Emit to stderr for immediate visibility in Celery logs."""
    timestamp = datetime.now(UTC).strftime("%H:%M:%S.%f")[:-3]
    parts = [f"[DEBUG {timestamp}]"]
    if function_name:
        parts.append(f"[{function_name}]")
    parts.append(message)
    if elapsed_ms is not None:
        parts.append(f"({elapsed_ms:.1f}ms)")
    if attributes:
        extras = " ".join(f"{k}={v}" for k, v in attributes.items() if v is not None)
        if extras:
            parts.append(f"| {extras}")
    print(" ".join(parts), file=sys.stderr)


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

    func_name, _, _ = _get_caller_info()
    attrs = _format_attributes(function_name=func_name, **kwargs)
    _emit_stderr(message, function_name=func_name, **kwargs)
    _emit_debug_event(
        message,
        task_id=task_id,
        project_id=project_id,
        **attrs,
    )


def debug_detailed(
    message: str,
    *,
    task_id: str | None = None,
    project_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Emit a detailed debug message (level 2).

    Use for messages that include timing or payload previews.
    """
    if not is_debug_enabled(2):
        return

    func_name, _, _ = _get_caller_info()
    attrs = _format_attributes(function_name=func_name, **kwargs)
    _emit_stderr(message, function_name=func_name, **kwargs)
    _emit_debug_event(
        message,
        task_id=task_id,
        project_id=project_id,
        **attrs,
    )


def debug_verbose(
    message: str,
    *,
    task_id: str | None = None,
    project_id: str | None = None,
    **kwargs: Any,
) -> None:
    """Emit a verbose debug message (level 3).

    Use for full payloads and detailed state dumps.
    """
    if not is_debug_enabled(3):
        return

    func_name, _, _ = _get_caller_info()
    attrs = _format_attributes(function_name=func_name, **kwargs)
    _emit_stderr(message, function_name=func_name, **kwargs)
    _emit_debug_event(
        message,
        task_id=task_id,
        project_id=project_id,
        **attrs,
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

    func_name, _, _ = _get_caller_info()
    attrs = _format_attributes(function_name=func_name, status="success", **kwargs)
    _emit_stderr(f"✓ {message}", function_name=func_name, **kwargs)
    _emit_debug_event(
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

    func_name, _, _ = _get_caller_info()
    error_str = str(error) if error else None
    attrs = _format_attributes(function_name=func_name, status="error", error=error_str, **kwargs)
    _emit_stderr(f"✗ {message}", function_name=func_name, error=error_str, **kwargs)
    _emit_debug_event(
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

    func_name, _, _ = _get_caller_info()
    attrs = _format_attributes(function_name=func_name, status="warning", **kwargs)
    _emit_stderr(f"⚠ {message}", function_name=func_name, **kwargs)
    _emit_debug_event(
        f"⚠ {message}",
        level="warning",
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

    attrs = _format_attributes(section=section_name, **kwargs)
    marker = f"═══ {section_name.upper()} ═══"
    _emit_stderr(marker)
    _emit_debug_event(
        marker,
        source="section",
        task_id=task_id,
        project_id=project_id,
        **attrs,
    )


@contextmanager
def debug_timer(
    operation: str,
    *,
    task_id: str | None = None,
    project_id: str | None = None,
    **kwargs: Any,
) -> Generator[None, None, None]:
    """Context manager for timing synchronous operations (level 2).

    Example:
        with debug_timer("fetch data", task_id="task-123"):
            data = fetch_data()
    """
    if not is_debug_enabled(2):
        yield
        return

    func_name, _, _ = _get_caller_info()
    start = time.perf_counter()
    _emit_stderr(f"→ {operation}", function_name=func_name)
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        attrs = _format_attributes(
            elapsed_ms=elapsed_ms,
            function_name=func_name,
            operation=operation,
            **kwargs,
        )
        _emit_stderr(f"← {operation}", function_name=func_name, elapsed_ms=elapsed_ms)
        _emit_debug_event(
            f"← {operation}",
            task_id=task_id,
            project_id=project_id,
            **attrs,
        )


@asynccontextmanager
async def debug_async_timer(
    operation: str,
    *,
    task_id: str | None = None,
    project_id: str | None = None,
    **kwargs: Any,
) -> AsyncGenerator[None, None]:
    """Context manager for timing async operations (level 2).

    Example:
        async with debug_async_timer("call agent", task_id="task-123"):
            result = await call_agent()
    """
    if not is_debug_enabled(2):
        yield
        return

    func_name, _, _ = _get_caller_info()
    start = time.perf_counter()
    _emit_stderr(f"→ {operation}", function_name=func_name)
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        attrs = _format_attributes(
            elapsed_ms=elapsed_ms,
            function_name=func_name,
            operation=operation,
            **kwargs,
        )
        _emit_stderr(f"← {operation}", function_name=func_name, elapsed_ms=elapsed_ms)
        _emit_debug_event(
            f"← {operation}",
            task_id=task_id,
            project_id=project_id,
            **attrs,
        )


def debug_timer_decorator[**P, R](
    func: Callable[P, R] | None = None,
    *,
    operation: str | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]] | Callable[P, R]:
    """Decorator for timing functions (level 2).

    Can be used with or without arguments:
        @debug_timer_decorator
        def my_func(): ...

        @debug_timer_decorator(operation="custom name")
        def my_func(): ...
    """

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        op_name = operation or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            if not is_debug_enabled(2):
                return fn(*args, **kwargs)

            start = time.perf_counter()
            _emit_stderr(f"→ {op_name}", function_name=fn.__name__)
            try:
                return fn(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000
                _emit_stderr(f"← {op_name}", function_name=fn.__name__, elapsed_ms=elapsed_ms)

        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


def debug_async_timer_decorator[**P, R](
    func: Callable[P, Coroutine[Any, Any, R]] | None = None,
    *,
    operation: str | None = None,
) -> (
    Callable[[Callable[P, Coroutine[Any, Any, R]]], Callable[P, Coroutine[Any, Any, R]]]
    | Callable[P, Coroutine[Any, Any, R]]
):
    """Decorator for timing async functions (level 2).

    Can be used with or without arguments:
        @debug_async_timer_decorator
        async def my_func(): ...

        @debug_async_timer_decorator(operation="custom name")
        async def my_func(): ...
    """

    def decorator(
        fn: Callable[P, Coroutine[Any, Any, R]],
    ) -> Callable[P, Coroutine[Any, Any, R]]:
        op_name = operation or fn.__name__

        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            if not is_debug_enabled(2):
                return await fn(*args, **kwargs)

            start = time.perf_counter()
            _emit_stderr(f"→ {op_name}", function_name=fn.__name__)
            try:
                return await fn(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000
                _emit_stderr(f"← {op_name}", function_name=fn.__name__, elapsed_ms=elapsed_ms)

        return wrapper

    if func is not None:
        return decorator(func)
    return decorator
