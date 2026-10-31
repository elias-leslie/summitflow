"""Idle wake of a live harness for the coordination inbox; the single pane-injection path.

When the agent runs in an Aico window and Tether has deliveries (API 16), the
wake is a content-free ``[Message]`` line on Tether's gated queue
(cli.lib.coord_deliver): senders queue it when they record a request or ack,
and the agent's own watcher queues reminders and memory notices. Nothing here
types then; ``woke`` records which items a line was queued for.

Otherwise Claude Code wakes through its own asyncRewake hook. Codex has no
rewake hook, so its Stop hook arms one detached idle watcher
(scripts/lib/coord_inbox.py ``watch codex``) bound to its own tmux pane, and
UserPromptSubmit disarms it. While armed, that watcher is the only code that
types into a pane: one line, into its own pane, and only when the composer is
empty. Delivery state here is content-free.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def _state_dir() -> Path:
    """Share Pi's user runtime even when a caller shell omits XDG_RUNTIME_DIR."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "st-coord-inbox"
    user_runtime = Path(f"/run/user/{os.getuid()}")
    try:
        if user_runtime.is_dir() and user_runtime.stat().st_uid == os.getuid():
            return user_runtime / "st-coord-inbox"
    except OSError:
        pass
    return Path("/tmp") / "st-coord-inbox"


STATE = _state_dir()
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


def woke_path(agent_id: str) -> Path:
    return STATE / f"{state_key(agent_id)}.woke.json"


def load_woke(agent_id: str) -> dict[str, float]:
    """Inbox item keys a Tether ``[Message]`` line was queued for (cli.lib.coord_deliver), with the time."""
    try:
        data = json.loads(woke_path(agent_id).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


@contextmanager
def _woke_lock(agent_id: str) -> Iterator[None]:
    STATE.mkdir(parents=True, exist_ok=True)
    with open(STATE / f"{state_key(agent_id)}.woke.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _save_woke(agent_id: str, woke: dict[str, float]) -> None:
    path = woke_path(agent_id)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(woke))
    tmp.replace(path)


def mark_woke(agent_id: str, keys: list[str] | tuple[str, ...], now: float | None = None) -> float:
    """Record that a Tether line now wakes the agent for ``keys`` (content-free; a day is kept); the stamp used."""
    now = time.time() if now is None else now
    with _woke_lock(agent_id):
        woke = {k: v for k, v in load_woke(agent_id).items() if isinstance(v, (int, float)) and v > now - 86400}
        woke.update({key: now for key in keys})
        _save_woke(agent_id, woke)
    return now


def unmark_woke(agent_id: str, keys: list[str] | tuple[str, ...], stamp: float) -> None:
    """Undo mark_woke(..., stamp) for ``keys`` no later mark replaced (the line was not queued)."""
    with _woke_lock(agent_id):
        woke = load_woke(agent_id)
        for key in keys:
            if woke.get(key) == stamp:
                del woke[key]
        _save_woke(agent_id, woke)


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
