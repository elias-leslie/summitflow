"""Synchronous PreToolUse publication hook (Claude/Codex shared JSON protocol).

Stdlib-only by contract: scripts/lib/command-guard runs this with the OS
interpreter so agent shells keep their guard when backend/.venv is broken.
"""

from __future__ import annotations

import json
import shlex
import sys
from typing import Any

from ._command_guard_helpers import CommandGuardDecision
from ._publication_guard import evaluate_publication_command

_CONNECTOR_MUTATIONS = (
    "merge_pull_request", "create_release", "update_release", "delete_release",
    "push_files", "create_or_update_file", "create_repository",
)
_SHELL_TOOLS = ("bash", "exec_command", "shell")


def evaluate_payload(payload: Any) -> CommandGuardDecision:
    """Evaluate one hook payload; raise ValueError on malformed input."""
    if not isinstance(payload, dict):
        raise ValueError("Hook payload must be an object")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        raise ValueError("Missing tool input")
    tool = str(payload.get("tool_name", "")).lower()
    command = tool_input.get("command", tool_input.get("cmd"))
    if isinstance(command, list) and all(isinstance(item, str) for item in command):
        command = shlex.join(command)
    if command is None:
        # Non-shell hooks may match GitHub connector tools directly.
        if any(word in tool for word in _CONNECTOR_MUTATIONS):
            return CommandGuardDecision(True, "direct_publication", "Use the canonical ST publication workflow.", "publication", "")
        if any(word in tool for word in _SHELL_TOOLS):
            raise ValueError("Missing shell command")
        return CommandGuardDecision(False, None, None, None, "")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("Invalid command")
    return evaluate_publication_command(command, payload.get("cwd"))


def emit(decision: CommandGuardDecision) -> None:
    if decision.blocked:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": decision.message,
        }}))
    else:
        print("{}")


def publication_hook_main() -> int:
    """Valid deny output also on evaluation errors."""
    try:
        decision = evaluate_payload(json.load(sys.stdin))
    except Exception:
        decision = CommandGuardDecision(True, "publication_error", "Publication guard could not evaluate tool input; execution refused.", "publication", "")
    emit(decision)
    return 0


if __name__ == "__main__":
    raise SystemExit(publication_hook_main())
