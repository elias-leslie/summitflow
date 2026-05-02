"""Compact guardrail lines for task context output."""

from __future__ import annotations

from app.services.task_execution_readiness import is_final_task_status

TASK_FRESHNESS_LINE = (
    "FRESHNESS:verify-system-project-state|"
    "task-text=historical|"
    "reshape-or-abandon-if-stale"
)


def format_task_freshness_lines(status: object) -> list[str]:
    """Return task freshness guardrail lines for active work."""
    return [] if is_final_task_status(status) else [TASK_FRESHNESS_LINE]
