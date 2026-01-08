"""Implementation executor package - Autonomous task execution.

This package provides the execution engine for running tasks with:
- Iteration loop (up to max_iterations)
- External verification (pytest, pyright, ruff)
- Alternate model consultation on thrashing
- Rollback on exhaustion

Modules:
    executor: Main ImplementationExecutor class
    types: ExecutionResult dataclass and constants
    verification: Test running and criteria checking
    agent: AI agent execution and consultation
    context: Context building for affected files
    subtasks: Subtask iteration and step tracking
"""

from .executor import ImplementationExecutor
from .types import (
    AGENT_TIMEOUT_SECONDS,
    SUBPROCESS_TIMEOUT_SECONDS,
    ExecutionResult,
)

__all__ = [
    "AGENT_TIMEOUT_SECONDS",
    "SUBPROCESS_TIMEOUT_SECONDS",
    "ExecutionResult",
    "ImplementationExecutor",
]
