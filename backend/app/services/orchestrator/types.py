"""Orchestrator types and constants.

Shared data structures used across the orchestrator package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ExecutionState(str, Enum):
    """Orchestrator execution states."""

    IDLE = "idle"
    CLAIMING = "claiming"
    SETTING_UP = "setting_up"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    MERGING = "merging"
    FAILED = "failed"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"


@dataclass
class SubtaskResult:
    """Result of executing a single subtask."""

    subtask_id: str
    success: bool
    error: str | None = None
    iterations: int = 0
    model_used: str = ""
    commit_sha: str | None = None


@dataclass
class OrchestrationResult:
    """Result of full task orchestration."""

    task_id: str
    success: bool
    state: ExecutionState
    subtask_results: list[SubtaskResult] = field(default_factory=list)
    error: str | None = None
    total_iterations: int = 0
    worktree_reverted: bool = False
    merge_sha: str | None = None
