"""Task checkout type definitions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class TaskCheckoutInfo:
    """Information about a task's shared checkout branch."""

    path: Path
    branch: str
    task_id: str
    base_branch: str
    is_active: bool = True


__all__ = [
    "TaskCheckoutInfo",
]
