"""Async utilities for running coroutines in synchronous contexts.

Provides helpers for bridging sync and async code, particularly useful
for running async operations from Celery tasks or other sync contexts.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

T = TypeVar("T")


def run_async_in_sync_context(coro: Awaitable[T]) -> T:
    """Run an async coroutine in a synchronous context.

    Creates a new event loop, runs the coroutine, and cleans up.
    Use when you need to call async code from sync code (e.g., Celery tasks).

    Args:
        coro: The coroutine to run

    Returns:
        The result of the coroutine

    Example:
        >>> async def fetch_data():
        ...     return {"data": "value"}
        >>> result = run_async_in_sync_context(fetch_data())
        >>> print(result)
        {'data': 'value'}
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
