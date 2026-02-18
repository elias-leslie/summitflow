"""Debug decorators and context managers.

Provides timing decorators and context managers for performance tracking.
"""

from __future__ import annotations

import functools
import time
from collections.abc import AsyncGenerator, Callable, Coroutine, Generator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from .debug_utils import (
    emit_debug_event,
    emit_stderr,
    format_attributes,
    get_caller_info,
    is_debug_enabled,
)


@contextmanager
def debug_timer(
    operation: str,
    *,
    task_id: str | None = None,
    project_id: str | None = None,
    **kwargs: Any,
) -> Generator[None]:
    """Context manager for timing synchronous operations (level 2).

    Example:
        with debug_timer("fetch data", task_id="task-123"):
            data = fetch_data()
    """
    if not is_debug_enabled(2):
        yield
        return

    func_name, _, _ = get_caller_info()
    start = time.perf_counter()
    emit_stderr(f"→ {operation}", function_name=func_name)
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        attrs = format_attributes(
            elapsed_ms=elapsed_ms,
            function_name=func_name,
            operation=operation,
            **kwargs,
        )
        emit_stderr(f"← {operation}", function_name=func_name, elapsed_ms=elapsed_ms)
        emit_debug_event(
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
) -> AsyncGenerator[None]:
    """Context manager for timing async operations (level 2).

    Example:
        async with debug_async_timer("call agent", task_id="task-123"):
            result = await call_agent()
    """
    if not is_debug_enabled(2):
        yield
        return

    func_name, _, _ = get_caller_info()
    start = time.perf_counter()
    emit_stderr(f"→ {operation}", function_name=func_name)
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        attrs = format_attributes(
            elapsed_ms=elapsed_ms,
            function_name=func_name,
            operation=operation,
            **kwargs,
        )
        emit_stderr(f"← {operation}", function_name=func_name, elapsed_ms=elapsed_ms)
        emit_debug_event(
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
        op_name = operation or fn.__name__  # ty: ignore[unresolved-attribute]

        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            if not is_debug_enabled(2):
                return fn(*args, **kwargs)

            start = time.perf_counter()
            emit_stderr(f"→ {op_name}", function_name=fn.__name__)  # ty: ignore[unresolved-attribute]
            try:
                return fn(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000
                emit_stderr(f"← {op_name}", function_name=fn.__name__, elapsed_ms=elapsed_ms)

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
        op_name = operation or fn.__name__  # ty: ignore[unresolved-attribute]

        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            if not is_debug_enabled(2):
                return await fn(*args, **kwargs)

            start = time.perf_counter()
            emit_stderr(f"→ {op_name}", function_name=fn.__name__)  # ty: ignore[unresolved-attribute]
            try:
                return await fn(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000
                emit_stderr(f"← {op_name}", function_name=fn.__name__, elapsed_ms=elapsed_ms)

        return wrapper

    if func is not None:
        return decorator(func)
    return decorator
