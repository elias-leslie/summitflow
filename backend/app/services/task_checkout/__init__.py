"""Task branch checkout service for autonomous execution."""

from __future__ import annotations

from .operations import (
    create_task_checkout,
    get_task_checkout,
    remove_task_checkout,
)
from .paths import ensure_task_checkout, get_execution_path
from .types import TaskCheckoutInfo

__all__ = [
    "TaskCheckoutInfo",
    "create_task_checkout",
    "ensure_task_checkout",
    "get_execution_path",
    "get_task_checkout",
    "remove_task_checkout",
]
