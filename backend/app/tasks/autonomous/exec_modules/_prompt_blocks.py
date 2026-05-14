"""Prompt context block builders (steps, failures, event classification)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

# Event classification markers
SESSION_END_MARKER = "SESSION END"
FAILURE_LEVELS = ("error", "warn")
FAILURE_KEYWORD = "FAILED"

# Limits for context truncation
WIND_DOWN_MSG_LIMIT = 500
ERROR_MSG_LIMIT = 200
MAX_PRIOR_ERRORS = 3
EVENTS_FETCH_LIMIT = 50

def _step_description(step: dict[str, Any]) -> str:
    description = str(step.get("description") or "").strip()
    if not description:
        return "Unnamed step"
    return description


def build_steps_block(steps: list[dict[str, Any]]) -> str:
    """Build a compact execution checklist for the prompt."""
    if not steps:
        return "Execute the subtask description directly."

    lines: list[str] = []
    for index, step in enumerate(steps, start=1):
        step_number = int(step.get("step_number") or index)
        lines.append(f"{step_number}. {_step_description(step)}")
        spec = step.get("spec")
        if isinstance(spec, dict):
            verify_commands = spec.get("verify_commands")
            if isinstance(verify_commands, list):
                commands = [str(command).strip() for command in verify_commands if str(command).strip()]
                if commands:
                    lines.append(f"   Verify with: {'; '.join(commands)}")

    return "\n".join(lines)


def classify_events(events: Sequence[Mapping[str, Any]]) -> tuple[list[str], list[str]]:
    """Classify events into wind-down messages and error messages."""
    wind_down_msgs: list[str] = []
    error_msgs: list[str] = []
    for evt in events:
        msg = evt.get("message", "") or ""
        if SESSION_END_MARKER in msg:
            wind_down_msgs.append(msg[:WIND_DOWN_MSG_LIMIT])
        elif evt.get("level") in FAILURE_LEVELS and FAILURE_KEYWORD in msg.upper():
            error_msgs.append(msg[:ERROR_MSG_LIMIT])
    return wind_down_msgs, error_msgs
