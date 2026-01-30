"""Orchestrator Service for Autonomous Task Execution.

This module re-exports from the orchestrator package for backwards compatibility.
The actual implementation is in the orchestrator/ package.

Uses Agent Hub agents for execution:
- agent:coder (AGENT_WORKER) handles coding tasks with mandate injection
- agent:supervisor (AGENT_SUPERVISOR) coordinates and handles stuck patterns
- Agent Hub provides model fallback chains, mandate injection, and metrics

Decision d1: Agent Hub agents with mandate injection
Decision d2: Claude SDK native interrupt() via WebSocket priority message
Decision d3: Coder agent for all coding, supervisor for stuck patterns
Decision d5: Self-heal 3 iterations, then auto-revert worktree
"""

from .orchestrator import (
    ExecutionState,
    OrchestrationResult,
    OrchestratorService,
    SubtaskResult,
)

__all__ = [
    "ExecutionState",
    "OrchestrationResult",
    "OrchestratorService",
    "SubtaskResult",
]
