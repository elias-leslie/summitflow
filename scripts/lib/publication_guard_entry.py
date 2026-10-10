"""Venv-independent entry for the PreToolUse publication hook.

Run as ``/usr/bin/python3 -I -S publication_guard_entry.py``. The full policy
(backend/app/services/publication_hook.py) is stdlib-only, so it normally runs
unchanged here even when backend/.venv is missing or emptied. If the backend
source itself cannot be imported, a conservative stdlib deny-list keeps
publication and destructive commands blocked while letting recovery and
ordinary commands run, and the degradation is reported loudly.

Output contract (stdout, exit 0): ``{}`` to allow, or a PreToolUse deny object.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"

_REPAIR = "Repair: cd backend && uv sync --locked, then st service rebuild summitflow."
_DENY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), label)
    for pattern, label in (
        (r"\b(?:git|jj)\b[\s\S]*\b(?:push|send-pack)\b", "direct publication"),
        (r"\bgh\b[\s\S]*\b(?:api|pr\s+merge|release|repo\s+(?:create|delete|archive|unarchive|rename|edit))\b", "direct publication"),
        (r"api\.github\.com", "direct publication"),
        (r"--no-verify|--dangerously-bypass-hook-trust|--disable-hooks|--disable\s+hooks", "hook disable"),
        (r"(?:SF_COMMAND_GUARD_DISABLE|GIT_ALLOW_SECRET|SECRETGUARD_DISABLE)\s*=", "hook disable"),
        (r"core\.hookspath|hooks\.enabled|features\.hooks", "hook disable"),
        (r"\brm\s+(?:-\S+\s+)*-\S*[rR]\S*\s+(?:-\S+\s+)*(?:/|/\*|~|~/|/srv|/srv/\S*|/home|\$HOME)(?:\s|$|;|&|\|)", "recursive deletion of a root path"),
        (r"\b(?:mkfs(?:\.\S+)?|wipefs|blkdiscard)\b", "filesystem destruction"),
        (r"\bdd\b[^\n]*\bof=/dev/", "raw device overwrite"),
        (r"\bbtrfs\s+(?:subvolume|sub)\s+(?:delete|del)\b", "snapshot deletion"),
        (r"\bgit\b[\s\S]*\b(?:reset\s+--hard|clean\s+-\S*f)", "destructive git"),
        (r"\b(?:eval|base64\s+(?:-d|--decode))\b", "unanalysable command"),
    )
)
_CONNECTOR_MUTATIONS = (
    "merge_pull_request", "create_release", "update_release", "delete_release",
    "push_files", "create_or_update_file", "create_repository",
)
_SHELL_TOOLS = ("bash", "exec_command", "shell")


def _deny(reason: str) -> str:
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }})


def fallback_decision(payload: object) -> str | None:
    """Return a deny reason, or None to allow. Never echoes the command."""
    if not isinstance(payload, dict) or not isinstance(payload.get("tool_input"), dict):
        return "malformed hook input"
    tool = str(payload.get("tool_name", "")).lower()
    tool_input = payload["tool_input"]
    command = tool_input.get("command", tool_input.get("cmd"))
    if isinstance(command, list) and all(isinstance(item, str) for item in command):
        command = shlex.join(command)
    if command is None:
        if any(word in tool for word in _CONNECTOR_MUTATIONS):
            return "direct publication"
        if any(word in tool for word in _SHELL_TOOLS):
            return "missing shell command"
        return None
    if not isinstance(command, str) or not command.strip():
        return "invalid command"
    for pattern, label in _DENY_PATTERNS:
        if pattern.search(command):
            return label
    return None


def _report_degraded(cause: str) -> None:
    message = f"summitflow publication guard DEGRADED: full policy unavailable ({cause}); conservative fallback active. {_REPAIR}"
    print(message, file=sys.stderr)
    try:
        import syslog

        syslog.openlog("summitflow-command-guard")
        syslog.syslog(syslog.LOG_CRIT, message)
    except Exception:  # diagnostics must never change the decision
        pass
    try:
        state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "summitflow"
        state.mkdir(parents=True, exist_ok=True)
        with (state / "command-guard-degraded.log").open("a") as log:
            log.write(json.dumps({"at": time.time(), "cause": cause}) + "\n")
    except Exception:
        pass


def main() -> int:
    raw = sys.stdin.read()
    if os.environ.get("SF_COMMAND_GUARD_FORCE_FALLBACK") != "1":
        try:
            sys.path.insert(0, str(BACKEND))
            from app.services.publication_hook import publication_hook_main
        except Exception as exc:
            cause = f"{type(exc).__name__}: {exc}"
        else:
            import io

            sys.stdin = io.StringIO(raw)
            return publication_hook_main()
    else:
        cause = "fallback forced by SF_COMMAND_GUARD_FORCE_FALLBACK"
    _report_degraded(cause)
    try:
        reason = fallback_decision(json.loads(raw))
    except Exception:
        reason = "unparseable hook input"
    if reason is None:
        print("{}")
    else:
        print(_deny(f"Publication guard degraded; conservative fallback refused this command ({reason}). {_REPAIR}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
