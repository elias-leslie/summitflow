"""Idle wake of a live harness for the coordination inbox; the single pane-injection path.

Claude Code wakes through its own asyncRewake hook. Codex has no rewake hook,
so its Stop hook arms one detached idle watcher (scripts/lib/coord_inbox.py
``watch codex``) bound to its own tmux pane, and UserPromptSubmit disarms it.
While armed, that watcher is the only code that types into a pane: one line,
into its own pane, and only when the composer is empty. Senders never type;
they write the ledger and the armed watcher wakes the pane so the agent's own
hook reads it. Delivery state here is content-free.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

STATE = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "st-coord-inbox"
# Longer wake text is not typed: the pane gets a short pointer and the body stays on the ledger.
TYPE_MAX = 400
# What a TUI composer line may hold before the cursor when it is empty.
_EMPTY_PROMPTS = {"", ">", "\u203a", "\u276f"}


def state_key(agent_id: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in agent_id)


def seen_path(agent_id: str) -> Path:
    return STATE / f"{state_key(agent_id)}.seen.json"


def load_seen(agent_id: str) -> dict[str, float]:
    try:
        data = json.loads(seen_path(agent_id).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def codex_pidfile(agent_id: str) -> Path:
    return STATE / f"{state_key(agent_id)}.codex-watch.pid"


def codex_watch_pid(agent_id: str) -> int | None:
    """PID of the armed Codex idle watcher for this agent, or None when it is not idle-armed."""
    try:
        pid = int(codex_pidfile(agent_id).read_text().strip())
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except (OSError, ValueError):
        return None
    if any(arg.endswith(b"coord_inbox.py") for arg in argv) and b"watch" in argv:
        return pid
    return None


def pane_line(rendered: str, requests: int) -> str:
    """The one line typed into an idle pane: the rendered items, or a short ledger pointer when long."""
    line = " ; ".join(rendered.splitlines())
    if len(line) <= TYPE_MAX:
        return line
    if requests:
        return (f"st coordination: {requests} request(s) waiting on you; read them with `st sessions inbox`, "
                "then answer with `st sessions ack <id> yes|no 'reason'|eta:MIN`")
    return "st coordination: updates on requests you sent; read them with `st sessions inbox`"


def wait_surfaced(agent_id: str, key: str, timeout: float, poll: float = 0.25) -> bool:
    """True once the target's own watcher or hook has surfaced ``key`` (from its seen state)."""
    deadline = time.monotonic() + timeout
    while True:
        if key in load_seen(agent_id):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll)


def _tmux(sock: str, *args: str) -> str | None:
    try:
        proc = subprocess.run(["tmux", "-S", sock, *args], capture_output=True, text=True, check=False, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def pane_ready(sock: str, pane: str) -> bool:
    """The pane is live, not in copy mode, shows its cursor, and nothing precedes it on the composer line."""
    info = _tmux(sock, "display-message", "-p", "-t", pane,
                 "#{pane_dead} #{pane_in_mode} #{cursor_flag} #{cursor_x} #{cursor_y}")
    parts = (info or "").split()
    if len(parts) != 5 or parts[:3] != ["0", "0", "1"] or not all(p.isdigit() for p in parts[3:]):
        return False
    x, y = int(parts[3]), int(parts[4])
    row = _tmux(sock, "capture-pane", "-p", "-t", pane, "-S", str(y), "-E", str(y))
    if row is None:
        return False
    return row.rstrip("\n")[:x].strip() in _EMPTY_PROMPTS


def type_line(text: str, sock: str, pane: str) -> bool:
    """Type one line into an idle pane with an empty composer and submit it; False types nothing."""
    if not sock or not pane or not pane_ready(sock, pane):
        return False
    line = " ".join(text.split())
    if _tmux(sock, "send-keys", "-t", pane, "-l", line) is None:
        return False
    time.sleep(0.6)  # let the TUI close its paste burst so Enter submits
    return _tmux(sock, "send-keys", "-t", pane, "Enter") is not None
