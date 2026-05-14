"""Agent routing utilities."""

from __future__ import annotations

from ._routing_maps import (
    SUBTASK_TYPE_AGENT_MAP,
    TASK_TYPE_AGENT_MAP,
)

DEFAULT_AGENT = "coder"
_GENERIC_IMPLEMENTATION_TYPES = {"backend", "frontend", "config", "devops", "database"}
_MAINTENANCE_TASK_AGENT_MAP = {
    "bug": "debugger",
    "debt": "refactor",
    "refactor": "refactor",
    "regression": "debugger",
}


def get_agent_for_subtask(subtask_type: str | None, task_type: str | None = None) -> str:
    """Get agent slug: subtask_type mapping > task_type mapping > default."""
    if subtask_type in _GENERIC_IMPLEMENTATION_TYPES and task_type in _MAINTENANCE_TASK_AGENT_MAP:
        return _MAINTENANCE_TASK_AGENT_MAP[task_type]
    if subtask_type and subtask_type in SUBTASK_TYPE_AGENT_MAP:
        return SUBTASK_TYPE_AGENT_MAP[subtask_type]
    if task_type and task_type in TASK_TYPE_AGENT_MAP:
        return TASK_TYPE_AGENT_MAP[task_type]
    return DEFAULT_AGENT


def get_agent_for_task(task_type: str | None) -> str:
    """Get agent slug for a task type."""
    return TASK_TYPE_AGENT_MAP.get(task_type, DEFAULT_AGENT) if task_type else DEFAULT_AGENT
