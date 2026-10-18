"""Memory notices for the coordination inbox hook (scripts/lib/coord_inbox.py).

Tells an agent, once, when memory pressure killed a process in its pane, stopped the pane, or warned about it.
Nightshift owns the record: memctl writes kernel kills and stopped panes to the memory event record, Tether's memory
guard adds its tool-job kills, warnings and agent-hog (killer tether), and `nightshift memory events --mine --json`
reads it (v1 records: ts, kind, killer, scope, pid, comm, cmdline_head, bytes, class, ...). This module only
renders them for the agent.

Hot path (every hook call and every watcher poll): /proc/self/cgroup, the pane's memory.events oom_kill counter,
a stat of the record file and this agent's small state file. Nightshift is asked only when the counter or the
record file changed. An agent or subagent starts from what is there at its first hook (SessionStart, SubagentStart),
so it never hears about an older kill in its pane; a resumed session hears the last day. A kernel kill the record does not show yet still gives a short counter-only notice at once,
and the record's later line for it stays quiet, so each kill is told once. Never raises into the hook; a broken
read means no notice.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

RESUME_LOOKBACK_S = 86400  # a resumed session hears about the last day, which covers the loss that ended its last run
HEARTBEAT_FRESH_S = 60
STATE_TTL_S = 2 * 86400
MAX_LINES = 6
QUERY_TIMEOUT_S = 3.0
LOCK_WAIT_S = 1.5  # with a 3 s query, a waiting hook still ends inside its 5 s budget
NOTICE_KINDS = frozenset({"kill", "warning", "pane-stopped", "agent-hog"})  # outside-hog is never in a pane
# memctl writes a kernel kill's record from its next tick (every 10 s), so its time can trail the counter by a tick
QUIET_SLACK_S = 15
WAKE_LINE = "Memory notice for this pane: the details are in this turn's hook context."

_REASON = {
    "tether": "the workstation was critically low on memory",
    "memctl": "the workstation was critically low on memory",
    "kernel-pane-cap": "{pane} reached its memory limit",
    "kernel-cgroup": "a shared memory limit was reached",
    "kernel-global": "the workstation ran out of memory",
    "oomd": "memory pressure stayed too high",
}
_KILLER = {"tether": "Tether's memory guard", "memctl": "memctl", "oomd": "systemd-oomd"}
GUARD_KILLERS = frozenset({"tether", "memctl"})  # tool-job kills (memctl's before 2026-10-17), not the kernel


@dataclass(frozen=True)
class Paths:
    state_dir: Path
    proc_cgroup: Path = Path("/proc/self/cgroup")
    cgroup_root: Path = Path("/sys/fs/cgroup")
    events: Path = field(default_factory=lambda: Path(
        os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "nightshift/memory-events.jsonl")
    heartbeat: Path = field(default_factory=lambda: Path(
        os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "nightshift/memctl.json")
    nightshift: str = ""  # "" finds it on PATH (or ~/.local/bin) when a record is needed, never on the hot path


@dataclass
class Notice:
    """Text to deliver; done() records it as shown (delivered=True) or leaves it for the next hook."""

    text: str
    _save: Callable[[], None]
    _lock: IO[str]

    def done(self, delivered: bool = True) -> None:
        try:
            if delivered:
                self._save()
        finally:
            self._lock.close()


def own_pane(paths: Paths) -> tuple[str, Path] | None:
    """(tmux-spawn-*.scope, its cgroup dir) for this process, or None outside an agent pane."""
    for line in paths.proc_cgroup.read_text().splitlines():
        if line.startswith("0::"):
            parts = [p for p in line[3:].strip().split("/") if p]
            for i in range(len(parts) - 1, -1, -1):
                if parts[i].startswith("tmux-spawn-") and parts[i].endswith(".scope"):
                    return parts[i], paths.cgroup_root.joinpath(*parts[: i + 1])
    return None


def _oom_kills(cgroup: Path) -> int | None:
    with contextlib.suppress(OSError, ValueError):
        for line in (cgroup / "memory.events").read_text().splitlines():
            name, _, value = line.partition(" ")
            if name == "oom_kill":
                return int(value)
    return None


def _signature(path: Path) -> list[int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return [st.st_ino, st.st_size]


def _memctl_alive(paths: Paths, now: float) -> bool:
    try:
        return now - paths.heartbeat.stat().st_mtime < HEARTBEAT_FRESH_S
    except OSError:
        return False


def _records(paths: Paths, since: float) -> list[dict[str, Any]] | None:
    """This pane's records (and an earlier pane of the same Tether session) from Nightshift; None when unavailable."""
    exe = paths.nightshift or shutil.which("nightshift") or str(Path.home() / ".local/bin/nightshift")
    try:
        res = subprocess.run([exe, "memory", "events", "--mine", "--since", str(int(since)), "--json"],
                             capture_output=True, text=True, timeout=QUERY_TIMEOUT_S, check=False,
                             stdin=subprocess.DEVNULL)
        data = json.loads(res.stdout) if res.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else None


def _key(r: dict[str, Any]) -> str:
    return f"{r.get('kind')}:{r.get('ts')}:{r.get('pid')}:{r.get('scope')}"


def _size(n: Any) -> str:
    if not isinstance(n, (int, float)) or n <= 0:
        return ""
    return f"{n / 2**30:.1f} GiB" if n >= 2**30 else f"{n / 2**20:.0f} MiB"


def _clock(ts: float) -> str:
    return time.strftime("%H:%M", time.localtime(ts))


def _who(r: dict[str, Any], pane: str) -> str:
    cmd = " ".join(str(r.get("cmdline_head") or "").split())
    cmd = cmd if len(cmd) <= 80 else cmd[:77] + "..."
    inner = ", ".join(x for x in (f"pid {r['pid']}" if r.get("pid") else "", f"`{cmd}`" if cmd else "") if x)
    name = str(r.get("comm") or "a process")
    who = f"{name} ({inner})" if inner else name
    owner = "this pane's agent" if pane == "this pane" else "this session's agent"
    return f"{owner}, {who}" if r.get("class") == "agent" else who


def line_for(r: dict[str, Any], scope: str) -> str:
    """One notice line for a v1 record; `scope` is this agent's pane now (a record can be from the pane before)."""
    at, kind, killer = _clock(float(r.get("ts") or 0)), r.get("kind"), str(r.get("killer") or "")
    pane = "this pane" if r.get("scope") == scope else "the pane this session ran in before"
    size = _size(r.get("bytes"))
    if kind == "kill":
        actor = _KILLER.get(killer, "the kernel")
        if r.get("pid"):
            victim = _who(r, pane) + (f", {size}" if size else "")
        else:
            count = int(r.get("count") or 1)
            victim = f"{count} process{'es' if count != 1 else ''} in {pane}"
        members = int(r.get("members") or 0)
        job = f", and the rest of its tool job ({members} processes in all)" if killer in GUARD_KILLERS and members > 1 else ""
        reason = _REASON.get(killer, "memory ran out").format(pane=pane)
        return f"{at} {actor} killed {victim}{job}; {reason}."
    if kind == "pane-stopped":
        return (f"{at} {pane} stopped as a whole after that kill, and its agent with it. This session was resumed "
                "afterwards: check git status and your notes before you continue.")
    if kind == "agent-hog":
        return (f"{at} memory is critical and {_who(r, pane)} is the biggest user ({size or 'size unknown'}). Tether does "
                "not kill agents, but the kernel will if memory runs out: save your notes now, compact, and keep big "
                "outputs out of your context.")
    # warning: Tether's memory guard names the fastest-growing pane while memory is getting low
    if r.get("class") == "agent":
        what = f"{_who(r, pane)} uses {size or 'the most'}. Save notes and compact soon; keep big outputs out of your context."
    elif r.get("pid"):
        what = f"{_who(r, pane)} uses {size or 'the most'}. If it is yours, finish or shrink it before Tether has to kill it."
    else:
        what = f"it uses {size or 'the most'}. Avoid starting more big jobs here for now."
    return f"{at} memory is getting low on the workstation and {pane} is growing fastest: {what}"


def counter_line(count: int, now: float, memctl_alive: bool) -> str:
    where = ("details: `nightshift memory events --mine` (memctl adds them within a minute)" if memctl_alive else
             f"memctl is not running, so details are only in `journalctl -k --since {_clock(now - 120)}`")
    return f"{_clock(now)} the kernel killed {count} process{'es' if count != 1 else ''} in this pane for memory; {where}."


def render(lines: list[str], kills: bool) -> str:
    if len(lines) > MAX_LINES:
        lines = [f"{len(lines) - MAX_LINES + 1} earlier events: `nightshift memory events --mine`.", *lines[-MAX_LINES + 1:]]
    text = ["Memory notice for this pane (information only; the process may be yours or a subagent's):", *lines]
    if kills:
        text.append("A command that ended early (exit 137, or a pipeline with missing output) was killed this way; "
                    "rerun it smaller or later. All records: `nightshift memory events --mine`.")
    return "\n".join(text)


def _load(path: Path) -> dict[str, Any] | None:
    with contextlib.suppress(OSError, ValueError):
        data = json.loads(path.read_text())
        if isinstance(data, dict) and isinstance(data.get("seen"), dict) and isinstance(data.get("quiet"), dict):
            return data
    return None


def _write(path: Path, state: dict[str, Any]) -> None:
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(state, separators=(",", ":")))
    tmp.replace(path)


def _acquire(lock: IO[str], wait: float = LOCK_WAIT_S) -> bool:
    deadline = time.monotonic() + wait
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)


def _unchanged(state: dict[str, Any] | None, scope: str, counter: int | None, sig: list[int] | None) -> bool:
    return bool(state) and state.get("scope") == scope and state.get("counter") == counter and state.get("sig") == sig


def check(agent: str, *, resumed: bool = False, paths: Paths, now: float | None = None) -> Notice | None:
    """A notice for `agent` (one state per agent and per subagent) when its pane has news; None otherwise.

    The caller delivers Notice.text and then calls done(); until then this agent's state is locked."""
    now = time.time() if now is None else now
    here = own_pane(paths)
    if here is None:
        return None
    scope, cgroup = here
    counter, sig = _oom_kills(cgroup), _signature(paths.events)
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in agent)
    state_path = paths.state_dir / f"mem-{safe}.json"
    if not resumed and _unchanged(_load(state_path), scope, counter, sig):
        return None
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    lock = open(paths.state_dir / "mem.lock", "w")  # noqa: SIM115 - one lock for all agents, held until Notice.done()
    try:
        if not _acquire(lock):
            lock.close()
            return None  # another hook is busy past any hook's budget: skip this time, the change is still there
        state = _load(state_path)
        if not resumed and _unchanged(state, scope, counter, sig):
            lock.close()
            return None
        if state is None:  # a new agent or subagent: drop the states of ones long gone
            for old in paths.state_dir.glob("mem-*.json"):
                with contextlib.suppress(OSError):
                    if now - old.stat().st_mtime > STATE_TTL_S:
                        old.unlink()
        lines, kills, new_state = _collect(state, scope, counter, sig, resumed, paths, now)
        if lines:
            return Notice(render(lines, kills), lambda: _write(state_path, new_state), lock)
        _write(state_path, new_state)
    except BaseException:
        lock.close()
        raise
    lock.close()
    return None


def _collect(state: dict[str, Any] | None, scope: str, counter: int | None, sig: list[int] | None, resumed: bool,
             paths: Paths, now: float) -> tuple[list[str], bool, dict[str, Any]]:
    """(notice lines, whether any is a kill, the state to save once they are shown) for what changed."""
    fresh = state is None
    if state is None:  # first call for this agent (SessionStart, SubagentStart): what happened before is not its news
        state = {"scope": scope, "counter": counter, "sig": sig, "since": now, "seen": {}, "quiet": {}}
    if resumed:
        state["since"] = min(float(state["since"]), now - RESUME_LOOKBACK_S)
    if state.get("scope") != scope:  # resumed into a new pane: its counter starts fresh
        state["scope"], state["counter"] = scope, counter
    since = max(float(state["since"]), now - RESUME_LOOKBACK_S)
    seen = {k: float(v) for k, v in state["seen"].items() if float(v) >= since}
    quiet = {k: float(v) for k, v in state["quiet"].items() if float(v) >= since}
    old = state["counter"]
    delta = max(counter - old, 0) if isinstance(counter, int) and isinstance(old, int) else 0
    ask = resumed or (not fresh and (sig != state["sig"] or delta > 0))
    lines: list[str] = []
    kills = False
    told_here = 0
    for r in (_records(paths, since) if ask else None) or []:
        key, ts = _key(r), float(r.get("ts") or 0)
        if key in seen or ts < since:
            continue
        seen[key] = ts
        if r.get("kind") not in NOTICE_KINDS:
            continue
        kernel_kill = r.get("kind") == "kill" and r.get("killer") not in GUARD_KILLERS
        scope_of = str(r.get("scope"))
        if kernel_kill and scope_of in quiet and ts <= quiet[scope_of] + QUIET_SLACK_S:
            continue  # already told from the counter
        if kernel_kill and scope_of == scope:
            told_here += int(r.get("count") or 1)
        kills = kills or r.get("kind") == "kill"
        lines.append(line_for(r, scope))
    if delta > told_here:
        lines.append(counter_line(delta - told_here, now, _memctl_alive(paths, now)))
        quiet[scope] = now
        kills = True
    state.update({"counter": counter, "sig": sig, "since": since, "seen": seen, "quiet": quiet})
    return lines, kills, state

