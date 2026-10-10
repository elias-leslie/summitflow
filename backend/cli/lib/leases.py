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
import re
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatch
from pathlib import Path

LEASES_DIR = Path(os.environ.get("ST_LEASES_DIR") or Path.home() / ".summitflow" / "leases")
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
    # "file" (edit scope), "hold" (repo-level declared purpose) or "op"
    # (acceptance/deployment; pid-fenced, blocks every editor while alive).
    kind: str = "file"
    purpose: str | None = None
    pid: int | None = None
    pid_start: str | None = None
    sensitive: bool = False
    # Harness process anchor "<pid>:<start tick>": identities on one live anchor
    # are one agent across context resets (coord_lineage).
    anchor: str | None = None

    def is_stale(self, now: datetime | None = None, ttl: timedelta = DEFAULT_IDLE_TTL) -> bool:
        if self.kind == "op":
            return not _process_alive(self.pid, self.pid_start)
        now = now or datetime.now(UTC)
        try:
            hb = datetime.fromisoformat(self.last_heartbeat)
        except ValueError:
            return True
        return (now - hb) > ttl

    def matches(self, path: str) -> bool:
        return any(fnmatch(path, g) or fnmatch(path, g.rstrip("/") + "/**") for g in self.globs)


def _process_start(pid: int) -> str | None:
    """Kernel start tick for pid, so a reused pid never revives a dead op lease."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return stat.rsplit(")", 1)[-1].split()[19]


def _process_alive(pid: int | None, start: str | None) -> bool:
    return bool(pid) and _process_start(int(pid or 0)) == start


_UUID7 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def short_id(sid: str) -> str:
    """Six distinguishing chars: a UUIDv7 (Codex, Pi) starts with a timestamp shared for hours, so use its random tail."""
    return sid[-6:] if _UUID7.fullmatch(sid) else sid[:6]


def identify_agent(*, native: bool = True) -> tuple[str, str, str, str]:
    """Return (agent_id, slug, session_id, provider) from env vars.

    Priority: explicit ST session → Claude Code → Codex CLI → Agent Hub → Pi
    → tmux pane → PID. Native session identifiers are validated and kept whole
    in session_id; the abbreviated agent_id remains the legacy lease identity.
    Agent Hub agents/specialists/persona pass AGENT_HUB_AGENT_SLUG +
    AGENT_HUB_SESSION_ID explicitly. CLI invocations from a Claude Code
    session inherit $CLAUDE_SESSION_ID.
    """
    def session(key: str) -> str | None:
        value = os.environ.get(key, "")
        return value if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value) else None

    short = short_id if native else (lambda sid: sid[:6])
    st_sid = session("ST_SESSION_ID")
    if st_sid:
        return f"st:{short(st_sid)}", "st", st_sid, "st"
    # A harness started from another harness's shell inherits that one's session
    # variable; the enclosing harness process decides which variable is ours.
    if native:
        from .coord_lineage import harness

        provider = harness()[1]
        own = {
            "claude_code": ("CLAUDE_CODE_SESSION_ID", "cc", "claude-code", "claude_code"),
            "codex": ("CODEX_THREAD_ID", "codex", "codex", "codex_cli"),
            "pi": ("PI_SESSION_ID", "pi", "pi", "pi"),
            "antigravity": ("ANTIGRAVITY_CONVERSATION_ID", "agy", "antigravity", "antigravity"),
        }.get(provider or "")
        sid = session(own[0]) if own else None
        if own and sid:
            return f"{own[1]}:{short(sid)}", own[2], sid, own[3]
    # native=False keeps the pre-coordination resolution for task-claim owners
    # already recorded under it; leases key on the harness's real session id.
    claude_sid = session("CLAUDE_SESSION_ID") or (native and session("CLAUDE_CODE_SESSION_ID"))
    if claude_sid:
        return f"cc:{short(claude_sid)}", "claude-code", claude_sid, "claude_code"
    codex_sid = session("CODEX_SESSION_ID") or (native and session("CODEX_THREAD_ID"))
    if codex_sid:
        return f"codex:{short(codex_sid)}", "codex", codex_sid, "codex_cli"
    ah_slug = os.environ.get("AGENT_HUB_AGENT_SLUG")
    ah_sid = session("AGENT_HUB_SESSION_ID")
    if ah_slug and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", ah_slug) and ah_sid:
        provider = "agent_hub_persona" if ah_slug == "jenny" else "agent_hub_specialist"
        return f"{ah_slug}:{short(ah_sid)}", ah_slug, ah_sid, provider
    pi_sid = session("PI_SESSION_ID")
    if pi_sid:
        return f"pi:{short(pi_sid)}", "pi", pi_sid, "pi"
    agy_sid = session("ANTIGRAVITY_CONVERSATION_ID")
    if agy_sid:
        return f"agy:{short(agy_sid)}", "antigravity", agy_sid, "antigravity"
    pane = os.environ.get("TMUX_PANE")
    if pane:
        return f"tmux:{pane.lstrip('%')}", "tmux", pane, "unknown"
    pid = str(os.getpid())
    return f"pid:{pid}", "pid", pid, "unknown"


def self_ids() -> set[str]:
    """Current identity, its predecessors on the same live harness process, and the legacy tmux alias."""
    from .coord_lineage import family_ids

    ids = {identify_agent()[0]} | family_ids()
    pane = os.environ.get("TMUX_PANE")
    if pane:
        ids.add(f"tmux:{pane.lstrip('%')}")
    return ids


def my_anchor() -> str | None:
    from .coord_lineage import current_anchor

    return current_anchor(identify_agent()[0])


def is_mine(lease: Lease, mine: set[str], anchor: str | None) -> bool:
    """Own lease: one of my identities, or recorded on my live harness process."""
    return lease.agent_id in mine or bool(anchor and lease.anchor == anchor)


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


def _read(project_id: str) -> dict:
    path = _store_path(project_id)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _load(project_id: str) -> list[Lease]:
    data = _read(project_id)
    leases: list[Lease] = []
    for item in data.get("leases", []):
        try:
            leases.append(Lease(**item))
        except TypeError:
            continue
    return leases


def _save(project_id: str, leases: list[Lease], touches: dict | None = None) -> None:
    """Write leases, keeping the touch history unless a new one is given (caller holds the lock)."""
    path = _store_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if touches is None:
        touches = _read(project_id).get("touches", {})
    doc: dict = {"leases": [asdict(lease) for lease in leases]}
    if touches:
        doc["touches"] = touches
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2))
    tmp.replace(path)


def _purge_stale(leases: list[Lease]) -> list[Lease]:
    return [lease for lease in leases if not lease.is_stale()]


def _project_path(path: str, project_root: str | None) -> str:
    """Use the project checkout for relative lease paths, independent of cwd."""
    if project_root and not Path(path).is_absolute():
        path = str(Path(project_root) / path)
    return os.path.normpath(path)


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
    globs = [_project_path(g, project_root) for g in globs]
    agent_id, slug, sid, provider = identify_agent()
    now = datetime.now(UTC).isoformat()
    with _lock(project_id):
        leases = _purge_stale(_load(project_id))
        for lease in leases:
            if lease.kind == "file" and lease.agent_id == agent_id and set(lease.globs) == set(globs):
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
            anchor=my_anchor(),
        )
        leases.append(lease)
        _save(project_id, leases)
        return lease


def list_active(project_id: str, kinds: tuple[str, ...] = ("file",)) -> list[Lease]:
    """Return live leases of the given kinds (stale ones purged on read)."""
    with _lock(project_id):
        loaded = _load(project_id)
        leases = _purge_stale(loaded)
        if len(leases) != len(loaded):
            _save(project_id, leases)
        return [lease for lease in leases if lease.kind in kinds]


def check(
    project_id: str, path: str, project_root: str | None = None
) -> tuple[bool, Lease | None]:
    """Return (ok_to_edit, conflicting_lease).

    ok_to_edit=False when another agent's lease matches the path, even if the
    current agent also has a matching lease. An uncontested own lease extends
    its heartbeat as a side effect.
    """
    path = _project_path(path, project_root)
    mine, anchor = self_ids(), my_anchor()
    now = datetime.now(UTC).isoformat()
    with _lock(project_id):
        leases = _purge_stale(_load(project_id))
        matching = [lease for lease in leases if lease.kind == "file" and lease.matches(path)]
        for lease in matching:
            if not is_mine(lease, mine, anchor):
                _save(project_id, leases)
                return False, lease
        if matching:
            matching[0].last_heartbeat = now
            _save(project_id, leases)
            return True, matching[0]
        _save(project_id, leases)
        return True, None


def heartbeat(project_id: str) -> int:
    """Touch all leases held by current agent. Returns count touched."""
    mine, anchor = self_ids(), my_anchor()
    now = datetime.now(UTC).isoformat()
    with _lock(project_id):
        leases = _purge_stale(_load(project_id))
        touched = 0
        for lease in leases:
            if is_mine(lease, mine, anchor):
                lease.last_heartbeat = now
                touched += 1
        _save(project_id, leases)
        return touched


def release(project_id: str, glob: str | None = None, project_root: str | None = None) -> int:
    """Release current agent's leases. Glob None → release all. Returns count released."""
    if glob is not None:
        glob = _project_path(glob, project_root)
    mine, anchor = self_ids(), my_anchor()
    with _lock(project_id):
        leases = _purge_stale(_load(project_id))
        before = len(leases)
        if glob is None:
            leases = [lease for lease in leases if not (lease.kind != "op" and is_mine(lease, mine, anchor))]
        else:
            leases = [
                lease for lease in leases
                if not (is_mine(lease, mine, anchor) and glob in lease.globs)
            ]
        _save(project_id, leases)
        return before - len(leases)


def release_task(project_id: str, task_id: str) -> int:
    """Release every lease tied to a task, regardless of holding agent.

    Called on `st done` so a completed task never leaves stale leases behind —
    including leases acquired by subagents under a different agent identity than
    the one closing the task (an orchestrator closes the subagent's task, but the
    subagent held the lease). Returns count released.
    """
    if not task_id:
        return 0
    with _lock(project_id):
        leases = _purge_stale(_load(project_id))
        before = len(leases)
        leases = [lease for lease in leases if lease.task_id != task_id]
        _save(project_id, leases)
        return before - len(leases)


def take(project_id: str, path: str, project_root: str | None = None) -> Lease:
    """Forcibly claim a path. Drops other agents' matching leases, logs takeover, then acquires."""
    path = _project_path(path, project_root)
    agent_id, _, _, _ = identify_agent()
    mine, anchor = self_ids(), my_anchor()
    with _lock(project_id):
        leases = _purge_stale(_load(project_id))
        kept: list[Lease] = []
        for lease in leases:
            if lease.kind != "op" and lease.matches(path) and not is_mine(lease, mine, anchor):
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


def wait(
    project_id: str,
    path: str,
    timeout: float = 1800.0,
    poll: float = 2.0,
    project_root: str | None = None,
) -> bool:
    """Block until path is free for the current agent. Returns True if freed, False on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ok, _ = check(project_id, path, project_root=project_root)
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


TOUCH_TTL = timedelta(hours=24)


def _session_sensitive() -> bool:
    """A session marks itself sensitive explicitly or by its project's identity."""
    if os.environ.get("ST_COORD_SENSITIVE") == "1":
        return True
    cwd = Path.cwd().resolve()
    for root in (cwd, *cwd.parents):
        identity = root / "project.identity.json"
        if identity.is_file():
            try:
                data = json.loads(identity.read_text())
            except (OSError, json.JSONDecodeError):
                return False
            coordination = data.get("coordination") if isinstance(data, dict) else None
            return bool(isinstance(coordination, dict) and coordination.get("sensitive"))
    return False


def claim(project_id: str, path: str, project_root: str | None = None) -> tuple[bool, Lease | None]:
    """Atomically check a single file and lease it to the current agent.

    Returns (ok, conflicting_lease). On success every own lease in the project
    is heartbeated and a 24 h touch record keeps dirty-file attribution after
    the lease itself expires or is released.
    """
    path = _project_path(path, project_root)
    agent_id, slug, sid, provider = identify_agent()
    mine, anchor = self_ids(), my_anchor()
    now_dt = datetime.now(UTC)
    now = now_dt.isoformat()
    with _lock(project_id):
        leases = _purge_stale(_load(project_id))
        for lease in leases:
            if lease.kind == "file" and lease.matches(path) and not is_mine(lease, mine, anchor):
                _save(project_id, leases)
                return False, lease
        own = None
        for lease in leases:
            if lease.kind != "op" and is_mine(lease, mine, anchor):
                lease.last_heartbeat = now
                if lease.kind == "file" and lease.matches(path):
                    own = lease
        if own is None:
            own = Lease(
                lease_id=uuid.uuid4().hex[:8], agent_id=agent_id, agent_slug=slug,
                session_id=sid, provider=provider, globs=[path], task_id=None,
                acquired_at=now, last_heartbeat=now, sensitive=_session_sensitive(), anchor=anchor,
            )
            leases.append(own)
        touches = {
            key: value for key, value in _read(project_id).get("touches", {}).items()
            if _touch_fresh(value, now_dt)
        }
        touches[path] = {"agent_id": agent_id, "session_id": sid, "at": now, "sensitive": own.sensitive, "anchor": anchor}
        _save(project_id, leases, touches)
        return True, own


def _touch_fresh(value: object, now: datetime) -> bool:
    if not isinstance(value, dict):
        return False
    stamp: object = value.get("at")  # type: ignore[union-attr]
    try:
        return now - datetime.fromisoformat(str(stamp)) <= TOUCH_TTL
    except ValueError:
        return False


def touches(project_id: str) -> dict[str, dict]:
    """Recent path -> {agent_id, session_id, at} edit records (attribution only)."""
    now = datetime.now(UTC)
    with _lock(project_id):
        raw = _read(project_id).get("touches", {})
    return {k: v for k, v in raw.items() if _touch_fresh(v, now)} if isinstance(raw, dict) else {}


def release_paths(project_id: str, paths: list[str], project_root: str | None = None) -> int:
    """Release the current agent's single-file leases on exactly these paths (after commit)."""
    targets = {_project_path(p, project_root) for p in paths}
    mine, anchor = self_ids(), my_anchor()
    with _lock(project_id):
        leases = _purge_stale(_load(project_id))
        kept = [
            lease for lease in leases
            if not (lease.kind == "file" and is_mine(lease, mine, anchor) and set(lease.globs) <= targets)
        ]
        _save(project_id, kept)
        return len(leases) - len(kept)


def acquire_mark(project_id: str, root: str, kind: str, purpose: str) -> Lease:
    """Acquire a repo-level hold (idle TTL) or op lease (fenced to this process)."""
    agent_id, slug, sid, provider = identify_agent()
    now = datetime.now(UTC).isoformat()
    pid = os.getpid() if kind == "op" else None
    lease = Lease(
        lease_id=uuid.uuid4().hex[:8], agent_id=agent_id, agent_slug=slug, session_id=sid,
        provider=provider, globs=[_project_path(root, None).rstrip("/") + "/**"], task_id=None,
        acquired_at=now, last_heartbeat=now, kind=kind, purpose=purpose[:40],
        pid=pid, pid_start=_process_start(pid) if pid else None, sensitive=_session_sensitive(),
        anchor=my_anchor(),
    )
    mine = self_ids()
    with _lock(project_id):
        leases = [
            item for item in _purge_stale(_load(project_id))
            if not (kind == "hold" and item.kind == "hold" and is_mine(item, mine, lease.anchor))
        ]
        leases.append(lease)
        _save(project_id, leases)
    return lease


def release_mark(project_id: str, lease_id: str) -> None:
    with _lock(project_id):
        _save(project_id, [lease for lease in _load(project_id) if lease.lease_id != lease_id])


def repo_marks(project_id: str) -> list[Lease]:
    """Live hold and op leases for a project."""
    return list_active(project_id, kinds=("hold", "op"))


def all_projects() -> list[str]:
    if not LEASES_DIR.is_dir():
        return []
    return sorted(p.stem for p in LEASES_DIR.glob("*.json") if not p.stem.startswith("_"))
