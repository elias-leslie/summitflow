"""File-based lease primitive for SummitFlow parallel coordination.

Replaces per-task branches as the parallel-work isolation mechanism. Branches
in a shared checkout were fake isolation: a branch-ref switch on one lane swept
another lane's uncommitted edits across lanes. Leases coordinate the real shared
resource (the filesystem) directly.

Storage: ~/.summitflow/leases/<project>.json with fcntl locking for atomic
read/modify/write across concurrent agents on the same machine. Cross-machine
support is a follow-up via an Agent Hub API wrapper.

Agent identity uses env vars so Claude Code, Codex CLI, Agent Hub persona
(Jenny), and Agent Hub specialists all coexist in the same lease table.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatch
from pathlib import Path

LEASES_DIR = Path.home() / ".summitflow" / "leases"
DEFAULT_IDLE_TTL = timedelta(minutes=30)


@dataclass
class Lease:
    lease_id: str
    agent_id: str
    agent_slug: str
    session_id: str
    provider: str
    globs: list[str]
    task_id: str | None
    acquired_at: str
    last_heartbeat: str
    taken_over_by: str | None = None

    def is_stale(self, now: datetime | None = None, ttl: timedelta = DEFAULT_IDLE_TTL) -> bool:
        now = now or datetime.now(UTC)
        try:
            hb = datetime.fromisoformat(self.last_heartbeat)
        except ValueError:
            return True
        return (now - hb) > ttl

    def matches(self, path: str) -> bool:
        return any(fnmatch(path, g) or fnmatch(path, g.rstrip("/") + "/**") for g in self.globs)


def identify_agent() -> tuple[str, str, str, str]:
    """Return (agent_id, slug, session_id, provider) from env vars.

    Priority: Claude Code → Codex CLI → Agent Hub → tmux pane → PID.
    Agent Hub agents/specialists/persona pass AGENT_HUB_AGENT_SLUG +
    AGENT_HUB_SESSION_ID explicitly. CLI invocations from a Claude Code
    session inherit $CLAUDE_SESSION_ID.
    """
    claude_sid = os.environ.get("CLAUDE_SESSION_ID")
    if claude_sid:
        return f"cc:{claude_sid[:6]}", "claude-code", claude_sid, "claude_code"
    codex_sid = os.environ.get("CODEX_SESSION_ID")
    if codex_sid:
        return f"codex:{codex_sid[:6]}", "codex", codex_sid, "codex_cli"
    ah_slug = os.environ.get("AGENT_HUB_AGENT_SLUG")
    ah_sid = os.environ.get("AGENT_HUB_SESSION_ID")
    if ah_slug and ah_sid:
        provider = "agent_hub_persona" if ah_slug == "jenny" else "agent_hub_specialist"
        return f"{ah_slug}:{ah_sid[:6]}", ah_slug, ah_sid, provider
    pane = os.environ.get("TMUX_PANE")
    if pane:
        return f"tmux:{pane.lstrip('%')}", "tmux", pane, "unknown"
    pid = str(os.getpid())
    return f"pid:{pid}", "pid", pid, "unknown"


def _store_path(project_id: str) -> Path:
    return LEASES_DIR / f"{project_id}.json"


def _lock_path(project_id: str) -> Path:
    return LEASES_DIR / f"{project_id}.lock"


@contextmanager
def _lock(project_id: str):
    LEASES_DIR.mkdir(parents=True, exist_ok=True)
    lock_file = _lock_path(project_id)
    with open(lock_file, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _load(project_id: str) -> list[Lease]:
    path = _store_path(project_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    leases: list[Lease] = []
    for item in data.get("leases", []):
        try:
            leases.append(Lease(**item))
        except TypeError:
            continue
    return leases


def _save(project_id: str, leases: list[Lease]) -> None:
    path = _store_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"leases": [asdict(lease) for lease in leases]}, indent=2))


def _purge_stale(leases: list[Lease]) -> list[Lease]:
    return [lease for lease in leases if not lease.is_stale()]


def acquire(
    project_id: str,
    globs: list[str],
    task_id: str | None = None,
    project_root: str | None = None,
) -> Lease:
    """Acquire or extend a lease for the current agent.

    Same agent + same glob set → heartbeat refresh (no duplicate row).

    Relative globs are resolved against project_root before storage so
    Lease.matches() (which compares against absolute paths from the hook)
    works regardless of which cwd the caller used.
    """
    if project_root:
        root_path = Path(project_root)
        globs = [g if Path(g).is_absolute() else str(root_path / g) for g in globs]
    agent_id, slug, sid, provider = identify_agent()
    now = datetime.now(UTC).isoformat()
    with _lock(project_id):
        leases = _purge_stale(_load(project_id))
        for lease in leases:
            if lease.agent_id == agent_id and set(lease.globs) == set(globs):
                lease.last_heartbeat = now
                if task_id and not lease.task_id:
                    lease.task_id = task_id
                _save(project_id, leases)
                return lease
        lease = Lease(
            lease_id=uuid.uuid4().hex[:8],
            agent_id=agent_id,
            agent_slug=slug,
            session_id=sid,
            provider=provider,
            globs=list(globs),
            task_id=task_id,
            acquired_at=now,
            last_heartbeat=now,
        )
        leases.append(lease)
        _save(project_id, leases)
        return lease


def list_active(project_id: str) -> list[Lease]:
    """Return live leases (stale ones purged on read)."""
    with _lock(project_id):
        leases = _purge_stale(_load(project_id))
        _save(project_id, leases)
        return leases


def check(project_id: str, path: str) -> tuple[bool, Lease | None]:
    """Return (ok_to_edit, conflicting_lease).

    ok_to_edit=False only when ANOTHER agent's lease matches the path. Same
    agent's lease is always OK (heartbeat extended as a side effect).
    """
    agent_id, _, _, _ = identify_agent()
    now = datetime.now(UTC).isoformat()
    with _lock(project_id):
        leases = _purge_stale(_load(project_id))
        for lease in leases:
            if lease.matches(path):
                if lease.agent_id == agent_id:
                    lease.last_heartbeat = now
                    _save(project_id, leases)
                    return True, lease
                _save(project_id, leases)
                return False, lease
        _save(project_id, leases)
        return True, None


def heartbeat(project_id: str) -> int:
    """Touch all leases held by current agent. Returns count touched."""
    agent_id, _, _, _ = identify_agent()
    now = datetime.now(UTC).isoformat()
    with _lock(project_id):
        leases = _purge_stale(_load(project_id))
        touched = 0
        for lease in leases:
            if lease.agent_id == agent_id:
                lease.last_heartbeat = now
                touched += 1
        _save(project_id, leases)
        return touched


def release(project_id: str, glob: str | None = None) -> int:
    """Release current agent's leases. Glob None → release all. Returns count released."""
    agent_id, _, _, _ = identify_agent()
    with _lock(project_id):
        leases = _purge_stale(_load(project_id))
        before = len(leases)
        if glob is None:
            leases = [lease for lease in leases if lease.agent_id != agent_id]
        else:
            leases = [
                lease for lease in leases
                if not (lease.agent_id == agent_id and glob in lease.globs)
            ]
        _save(project_id, leases)
        return before - len(leases)


def take(project_id: str, path: str) -> Lease:
    """Forcibly claim a path. Drops other agents' matching leases, logs takeover, then acquires."""
    agent_id, _, _, _ = identify_agent()
    with _lock(project_id):
        leases = _purge_stale(_load(project_id))
        kept: list[Lease] = []
        for lease in leases:
            if lease.matches(path) and lease.agent_id != agent_id:
                continue
            kept.append(lease)
        _save(project_id, kept)
    new_lease = acquire(project_id, [path])
    new_lease.taken_over_by = agent_id
    with _lock(project_id):
        current = _load(project_id)
        for lease in current:
            if lease.lease_id == new_lease.lease_id:
                lease.taken_over_by = agent_id
        _save(project_id, current)
    return new_lease


def wait(project_id: str, path: str, timeout: float = 1800.0, poll: float = 2.0) -> bool:
    """Block until path is free for the current agent. Returns True if freed, False on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ok, _ = check(project_id, path)
        if ok:
            return True
        time.sleep(poll)
    return False


def idle_string(lease: Lease, now: datetime | None = None) -> str:
    """Format idle duration for pulse display (e.g. '2m', '18s', '7h')."""
    now = now or datetime.now(UTC)
    try:
        hb = datetime.fromisoformat(lease.last_heartbeat)
    except ValueError:
        return "?"
    secs = int((now - hb).total_seconds())
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    return f"{secs // 3600}h"


def format_pulse_line(lease: Lease) -> str:
    """One-line pulse format: agent · lease:'<globs>' · task:<id|--> · idle:<duration>"""
    globs_str = ", ".join(lease.globs)
    task_str = lease.task_id or "--"
    return f"{lease.agent_id} · lease:'{globs_str}' · task:{task_str} · idle:{idle_string(lease)}"
