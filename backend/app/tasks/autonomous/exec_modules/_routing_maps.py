"""Routing map constants for agent_routing. Not imported directly by callers."""

from __future__ import annotations

TASK_TYPE_AGENT_MAP: dict[str, str] = {
    "refactor": "refactor",
    "debt": "refactor",
    "bug": "debugger",
    "regression": "debugger",
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
    "database": "coder",
    "image-gen": "image-gen",
    "game-design": "coder",
    "design-review": "designer",
    "exploration": "explorer",
}
