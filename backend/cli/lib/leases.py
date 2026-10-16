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

File leases are advisory; the same store keeps per-path writer sets (every
session that wrote a dirty path, kept until commit or revert) that st commit
uses to refuse sweeping another session's work.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
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


# Tether sets ST_SESSION_ID=aico-root-<uuid> on every root it launches: a fleet handle, not an agent identity.
ROOT_HANDLE_PREFIX = "aico-root-"


def short_id(sid: str) -> str:
    """Six distinguishing chars: a UUIDv7 (Codex, Pi) starts with a timestamp shared for hours, so use its random tail."""
    sid = sid.removeprefix(ROOT_HANDLE_PREFIX)
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
    # Every Tether root carries a root handle; its harness's own session id is the agent.
    if st_sid and not (native and st_sid.startswith(ROOT_HANDLE_PREFIX)):
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
    if st_sid:
        return f"st:{short(st_sid)}", "st", st_sid, "st"
    pane = os.environ.get("TMUX_PANE")
    if pane:
        return f"tmux:{pane.lstrip('%')}", "tmux", pane, "unknown"
    pid = str(os.getpid())
    return f"pid:{pid}", "pid", pid, "unknown"


def _lineage() -> tuple[str, str | None, set[str], set[str], bool]:
    """(agent id, live anchor, whole family, main-thread family, current id is a child thread).

    The family is every identity seen on this live harness process: context
    resets and Codex child threads alike. Main-thread keys are the ones whose
    SessionStart hook ran (coord.session_start marks them); once a process has
    any, an unmarked identity on it is a child thread. Without marks (a harness
    with no session hook) the whole family counts as main.
    """
    from .coord_lineage import current_anchor, load_doc

    agent_id = identify_agent()[0]
    anchor = current_anchor(agent_id)
    if not anchor:
        return agent_id, None, set(), set(), False
    rows = {
        aid: row for aid, row in (load_doc().get("identities") or {}).items()
        if isinstance(row, dict) and row.get("anchor") == anchor
    }
    mains = {aid for aid, row in rows.items() if row.get("main")}
    if not mains:
        return agent_id, anchor, set(rows), set(rows), False
    return agent_id, anchor, set(rows), mains, agent_id not in mains


def _with_tmux(ids: set[str]) -> set[str]:
    pane = os.environ.get("TMUX_PANE")
    if pane:
        ids.add(f"tmux:{pane.lstrip('%')}")
    return ids


def self_ids() -> set[str]:
    """Lease owners I act for: my id, main-thread predecessors on my live harness process, the legacy tmux alias.

    A Codex child thread owns only its own leases, so its release-all never drops a sibling's or its parent's.
    """
    agent_id, _, _, mains, child = _lineage()
    return _with_tmux({agent_id} | (set() if child else mains))


def my_anchor() -> str | None:
    """Anchor a lease is stamped and matched with; None for a child thread (see self_ids)."""
    _, anchor, _, _, child = _lineage()
    return None if child else anchor


def is_mine(lease: Lease, mine: set[str], anchor: str | None) -> bool:
    """Own lease: one of my identities, or recorded on my live harness process by a main-thread key."""
    return lease.agent_id in mine or bool(anchor and lease.anchor == anchor)


def session_ids() -> tuple[set[str], str | None]:
    """(identities, anchor) of my whole session for writer attribution: child threads and resets included."""
    agent_id, anchor, family, _, _ = _lineage()
    return _with_tmux({agent_id} | family), anchor


def root_key() -> str:
    """Writer key: a child thread records under its process's latest main-thread key."""
    agent_id, _, _, mains, child = _lineage()
    if not child:
        return agent_id
    from .coord_lineage import load_doc

    rows = load_doc().get("identities") or {}
    return max(mains, key=lambda aid: str((rows.get(aid) or {}).get("last") or ""), default=agent_id)


def _project_file(project_id: str, suffix: str) -> Path:
    """Path under LEASES_DIR for a project slug; refuses ids that could escape it."""
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}", project_id):
        raise ValueError(f"invalid project id: {project_id!r}")
    base = os.path.normpath(LEASES_DIR)
    path = os.path.normpath(os.path.join(base, project_id + suffix))
    if not path.startswith(base + os.sep):
        raise ValueError(f"invalid project id: {project_id!r}")
    return Path(path)


def _store_path(project_id: str) -> Path:
    return _project_file(project_id, ".json")


def _lock_path(project_id: str) -> Path:
    return _project_file(project_id, ".lock")


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


def _save(project_id: str, leases: list[Lease], writers: dict | None = None) -> None:
    """Write leases, keeping the writer sets unless new ones are given (caller holds the lock)."""
    path = _store_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if writers is None:
        writers = _load_writers(_read(project_id))
    doc: dict = {"leases": [asdict(lease) for lease in leases]}
    if writers:
        doc["writers"] = writers
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
    """Release current agent's leases: all (glob None), one lease id, or one glob.

    Releasing one glob of a multi-glob lease drops only that glob; the lease
    keeps its id and other globs. Returns the count of globs or leases released.
    """
    mine, anchor = self_ids(), my_anchor()
    with _lock(project_id):
        leases = _purge_stale(_load(project_id))
        before = len(leases)
        if glob is None:
            leases = [lease for lease in leases if not (lease.kind != "op" and is_mine(lease, mine, anchor))]
            _save(project_id, leases)
            return before - len(leases)
        if any(lease.lease_id == glob and lease.kind != "op" and is_mine(lease, mine, anchor) for lease in leases):
            _save(project_id, [lease for lease in leases if lease.lease_id != glob])
            return 1
        target = _project_path(glob, project_root)
        released = 0
        kept: list[Lease] = []
        for lease in leases:
            if is_mine(lease, mine, anchor) and target in lease.globs:
                released += 1
                lease.globs = [g for g in lease.globs if g != target]
                if not lease.globs:
                    continue
            kept.append(lease)
        _save(project_id, kept)
        return released


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
        # Taking a path adopts its dirty change: other writers no longer block my commit of it.
        writers = _load_writers(_read(project_id))
        writers[path] = [_writer_entry()]
        _save(project_id, current, writers)
    return new_lease


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


TOUCH_TTL = timedelta(hours=24)  # legacy last-writer records, folded into writer sets on read
UNKNOWN_WRITER = "unknown"


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


# ---------------------------------------------------------------- writer sets
# path -> [{agent_id, session_id, anchor, at, sensitive[, reason]}]: every session (or
# "unknown") that wrote a dirty path, kept until the path is committed or reverted.

def _writer_entry(*, unknown: str | None = None, sensitive: bool | None = None) -> dict:
    agent_id, _, sid, _ = identify_agent()
    _, anchor = session_ids()
    entry = {
        "agent_id": UNKNOWN_WRITER if unknown else root_key(), "session_id": sid, "anchor": anchor,
        "at": datetime.now(UTC).isoformat(),
        "sensitive": _session_sensitive() if sensitive is None else sensitive,
    }
    if unknown:
        entry.update(reason=unknown, by=agent_id)
    return entry


def _load_writers(doc: dict) -> dict[str, list[dict]]:
    raw = doc.get("writers")
    writers = {
        path: [e for e in entries if isinstance(e, dict) and e.get("agent_id")]
        for path, entries in (raw.items() if isinstance(raw, dict) else ()) if isinstance(entries, list)
    }
    legacy = doc.get("touches")
    now = datetime.now(UTC)
    for path, touch in (legacy.items() if isinstance(legacy, dict) else ()):
        if _touch_fresh(touch, now) and touch.get("agent_id"):
            _add_writer(writers, path, dict(touch))
    return {path: entries for path, entries in writers.items() if entries}


def _add_writer(writers: dict[str, list[dict]], path: str, entry: dict) -> None:
    entries = [e for e in writers.get(path, []) if e.get("agent_id") != entry["agent_id"]]
    writers[path] = [*entries, entry]


def is_own_writer(entry: dict, mine: set[str], anchor: str | None) -> bool:
    """A writer entry from my session (an unknown writer is never mine)."""
    if entry.get("agent_id") == UNKNOWN_WRITER:
        return False
    return entry.get("agent_id") in mine or bool(anchor and entry.get("anchor") == anchor)


def writer_label(entry: dict) -> str:
    if entry.get("agent_id") == UNKNOWN_WRITER:
        return f"{UNKNOWN_WRITER}({entry.get('reason') or '?'})"
    return str(entry.get("agent_id"))


def claim(project_id: str, path: str, project_root: str | None = None) -> tuple[bool, Lease | None]:
    """Atomically lease a single file to the current agent for an edit (advisory).

    Returns (ok, conflicting_lease): a conflict is another session's lease (my
    child threads' leases are not); it is reported, but the path is still
    leased and recorded because the edit goes ahead. Every own lease in the
    project is heartbeated and the current session joins the path's writer set.
    """
    path = _project_path(path, project_root)
    agent_id, slug, sid, provider = identify_agent()
    mine, anchor = self_ids(), my_anchor()
    session, session_anchor = session_ids()
    now = datetime.now(UTC).isoformat()
    with _lock(project_id):
        leases = _purge_stale(_load(project_id))
        conflict = next((lease for lease in leases if lease.kind == "file" and lease.matches(path)
                         and not is_mine(lease, session, session_anchor)), None)
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
        writers = _load_writers(_read(project_id))
        _add_writer(writers, path, _writer_entry(sensitive=own.sensitive))
        _save(project_id, leases, writers)
        return conflict is None, conflict or own


def record_writes(
    project_id: str,
    paths: list[str],
    *,
    since: datetime | None = None,
    unknown: str | None = None,
    dirty: set[str] | None = None,
    root: str | None = None,
) -> list[str]:
    """Add the current session (or an ``unknown`` writer with that reason) to each path's writer set.

    With ``since`` (a shell command's start) a path another session wrote or
    newly leased after that moment gets an ``unknown(concurrent)`` writer instead:
    either session may own the change, so broad commits by both stay refused
    while an explicit ``--paths`` commit remains open. With ``dirty`` and
    ``root``, writer sets of paths under root that are no longer dirty (committed
    or reverted) are dropped. Returns the recorded paths.
    """
    mine, anchor = session_ids()
    lease_mine, lease_anchor = self_ids(), my_anchor()
    entry = _writer_entry(unknown=unknown)
    concurrent = entry if unknown else _writer_entry(unknown="concurrent")
    recorded: list[str] = []
    with _lock(project_id):
        leases = _purge_stale(_load(project_id))
        writers = _load_writers(_read(project_id))
        if dirty is not None and root:
            _prune(writers, root, dirty)
        for path in paths:
            if since and (
                any(not is_own_writer(e, mine, anchor) and _at_or_after(e.get("at"), since)
                    for e in writers.get(path, []))
                or any(lease.kind == "file" and lease.matches(path) and not is_mine(lease, lease_mine, lease_anchor)
                       and _at_or_after(lease.acquired_at, since) for lease in leases)
            ):
                _add_writer(writers, path, dict(concurrent))
            else:
                _add_writer(writers, path, dict(entry))
            recorded.append(path)
        _save(project_id, leases, writers)
    return recorded


def _at_or_after(stamp: object, since: datetime) -> bool:
    try:
        return datetime.fromisoformat(str(stamp)) >= since
    except ValueError:
        return False


def _prune(writers: dict[str, list[dict]], root: str, dirty: set[str]) -> None:
    prefix = root.rstrip("/") + "/"
    for path in [p for p in writers if p.startswith(prefix) and p not in dirty]:
        del writers[path]


def prune_writers(project_id: str, root: str, dirty: set[str]) -> None:
    """Drop writer sets of paths under ``root`` that are no longer dirty (committed or reverted)."""
    with _lock(project_id):
        doc = _read(project_id)
        writers = _load_writers(doc)
        before = len(writers)
        _prune(writers, root, dirty)
        if len(writers) != before or "touches" in doc:
            _save(project_id, _load(project_id), writers)


def writers(project_id: str) -> dict[str, list[dict]]:
    """Path -> writer entries for every dirty path some session recorded."""
    with _lock(project_id):
        return _load_writers(_read(project_id))


def _touch_fresh(value: object, now: datetime) -> bool:
    if not isinstance(value, dict):
        return False
    stamp: object = value.get("at")  # type: ignore[union-attr]
    try:
        return now - datetime.fromisoformat(str(stamp)) <= TOUCH_TTL
    except ValueError:
        return False


def touches(project_id: str) -> dict[str, dict]:
    """Path -> latest known writer {agent_id, session_id, at, ...} (attribution only)."""
    out: dict[str, dict] = {}
    for path, entries in writers(project_id).items():
        known = [e for e in entries if e.get("agent_id") != UNKNOWN_WRITER]
        if known:
            out[path] = max(known, key=lambda e: str(e.get("at") or ""))
    return out


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
