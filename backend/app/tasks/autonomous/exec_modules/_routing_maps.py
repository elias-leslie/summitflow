"""Routing map constants for agent_routing. Not imported directly by callers."""

from __future__ import annotations

TASK_TYPE_AGENT_MAP: dict[str, str] = {
    "refactor": "refactor",
    "bug": "debugger",
    "feature": "coder",
}

SUBTASK_TYPE_AGENT_MAP: dict[str, str] = {
    "backend": "coder",
    "frontend": "coder",
    "ui-design": "ux-polisher",
    "refactor": "refactor",
    "bug-fix": "debugger",
    "test": "test-writer",
    "performance": "optimizer",
    "config": "coder",
    "devops": "coder",
}

VALID_SUBTASK_TYPES: set[str] = set(SUBTASK_TYPE_AGENT_MAP.keys())

# Cross-agent fallback: when primary agent fails after escalation,
# try these alternative agents (in order)
CROSS_AGENT_FALLBACK_MAP: dict[str, list[str]] = {
    "backend": ["debugger", "refactor"],
    "frontend": ["debugger", "ux-polisher"],
    "ui-design": ["coder"],
    "bug-fix": ["coder", "refactor"],
    "test": ["coder"],
    "performance": ["coder", "debugger"],
    "refactor": ["coder"],
    "config": ["debugger"],
    "devops": ["coder"],
}
