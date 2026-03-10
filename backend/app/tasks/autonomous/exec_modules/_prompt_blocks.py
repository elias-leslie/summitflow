"""Prompt context block builders (steps, failures, event classification)."""

from __future__ import annotations

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

FEEDBACK_PROMPT = """Before this work stint ends, submit any feedback on the tools and infrastructure you used during this task.

Use this session id for feedback and duplicate voting: {feedback_session_id}

Search first to avoid duplicates: st feedback search "keyword"

Then report:
- What caused friction? st feedback report <component> "issue" --type friction --severity medium --session {feedback_session_id} --vote-if-match
- Any improvement ideas? st feedback report <component> "idea" --type idea --session {feedback_session_id} --vote-if-match
- What worked well? st feedback report <component> "what worked" --type praise --session {feedback_session_id} --vote-if-match

Components: sf.cli, sf.dt, sf.quality, sf.worktree, sf.api, ah.memory, ah.sessions, ah.hooks, xc.tool_registry, xc.error_handling

If this session is read-only or cannot execute `st` commands, do not pretend feedback was filed. Summarize the friction or praise plainly in your final response instead.

If nothing to report, say "no feedback".

Task summary: {task_summary}"""


def build_steps_block(steps: list[dict[str, Any]]) -> str:
    """Build formatted steps block from step dicts."""
    if not steps:
        return ""
    lines = ["Steps to complete:"]
    for step in steps:
        step_num = step.get("step_number", 0)
        desc = step.get("description", "")
        lines.append(f"{step_num}. {desc}")
        spec = step.get("spec") or {}
        verify_commands = spec.get("verify_commands", [])
        if verify_commands:
            lines.append("   Verification commands:")
            lines.extend(f"   - `{command}`" for command in verify_commands)
    return "\n".join(lines)


def build_failures_block(failed_steps: list[dict[str, Any]]) -> str:
    """Build formatted failures block from failed step results."""
    parts = []
    for fail in failed_steps:
        step_num = fail.get("step_number", "?")
        reason = fail.get("reason", "unknown")
        output = fail.get("output", "")[:500]
        parts.append(f"### Step {step_num}: FAILED")
        parts.append(f"Reason: {reason}")
        if output:
            parts.append(f"Output:\n```\n{output}\n```")
    return "\n\n".join(parts)


def classify_events(events: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
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
