"""Coordination identity across context resets.

A context reset (Claude ``/clear``, Codex ``/new``/``/clear``, Pi ``/new``,
Antigravity clear) mints a new native session id inside the same harness
process. That process is the stable anchor: ``<pid>:<kernel start tick>`` of
the nearest ancestor harness process. Every identity seen on a live anchor is
one agent (its *family*), so the successor already owns its predecessor's
leases, holds and open handshakes; nothing is copied, nothing can be half
moved. Dead anchors drop out at once; unclaimed leases expire by idle TTL.

On a reset the successor gets one ``continuing ...`` line when something is
open, and each peer with an open exchange gets one ``context reset`` line.
Output is silent otherwise.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

from . import leases

HARNESS_COMMS = {"claude": "claude_code", "codex": "codex", "pi": "pi", "agy": "antigravity"}
# Identity prefixes a harness anchor may carry; st:/tmux:/pid:/agent-hub ids never join a family.
_PREFIX = {"claude_code": "cc:", "codex": "codex:", "pi": "pi:", "antigravity": "agy:"}
REGISTRY_TTL = timedelta(hours=24)
NOTE_TTL = timedelta(hours=24)
_SESSION_ENV = {
    "claude_code": "CLAUDE_CODE_SESSION_ID",
    "codex": "CODEX_THREAD_ID",
    "pi": "PI_SESSION_ID",
    "antigravity": "ANTIGRAVITY_CONVERSATION_ID",
}


# ---------------------------------------------------------------- anchor

def _stat(pid: int) -> tuple[str, int, str] | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    comm = raw[raw.find("(") + 1 : raw.rfind(")")]
    fields = raw.rsplit(")", 1)[-1].split()
    return comm, int(fields[1]), fields[19]


@cache
def _proc_anchor(start_pid: int) -> tuple[str, str] | None:
    """Nearest ancestor harness process; a shared app-server hosts unrelated threads, so it is no anchor."""
    pid = start_pid
    for _ in range(40):
        if pid <= 1:
            return None
        info = _stat(pid)
        if info is None:
            return None
        comm, ppid, start = info
        if comm in HARNESS_COMMS:
            try:
                cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
            except OSError:
                return None
            # Shared daemons (codex app-server / exec-server / mcp-server) host unrelated threads.
            if any(arg.endswith(b"-server") or arg == b"daemon" for arg in cmdline.split(b"\0")[1:]):
                return None
            return f"{pid}:{start}", HARNESS_COMMS[comm]
        pid = ppid
    return None


def harness() -> tuple[str | None, str | None]:
    """(anchor, harness provider) for this process; ST_COORD_ANCHOR overrides (tests, adapters)."""
    override = os.environ.get("ST_COORD_ANCHOR")
    if override is not None:
        return (override or None), os.environ.get("ST_COORD_HARNESS") or None
    found = _proc_anchor(os.getpid())
    return found if found else (None, None)


def anchor_alive(anchor: str | None) -> bool:
    if not anchor or ":" not in anchor:
        return False
    pid, _, start = anchor.partition(":")
    return pid.isdigit() and leases._process_alive(int(pid), start)


def session_env_for(provider: str | None) -> str | None:
    return _SESSION_ENV.get(provider or "")


# ---------------------------------------------------------------- registry

def _doc_path() -> Path:
    return leases.LEASES_DIR / "_coord.json"


def load_doc() -> dict[str, Any]:
    try:
        data = json.loads(_doc_path().read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_doc(doc: dict[str, Any]) -> None:
    """Atomic replace (caller holds the _coord lock); readers never lock."""
    path = _doc_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, indent=1))
    tmp.replace(path)


def _fresh(stamp: object, ttl: timedelta, now: datetime) -> bool:
    try:
        return now - datetime.fromisoformat(str(stamp)) <= ttl
    except ValueError:
        return False


def current_anchor(agent_id: str | None = None) -> str | None:
    """Live anchor from the process tree; inside a pid namespace or a reparented job, the id's registered one."""
    anchor = harness()[0]
    if anchor:
        return anchor if anchor_alive(anchor) else None
    if agent_id is None:
        agent_id = leases.identify_agent()[0]
    registered = ((load_doc().get("identities") or {}).get(agent_id) or {}).get("anchor")
    return registered if anchor_alive(registered) else None


def family_ids(anchor: str | None = None) -> set[str]:
    """Every identity registered on this live anchor (lock-free read; safe under any lock)."""
    anchor = anchor if anchor is not None else current_anchor()
    if not anchor or not anchor_alive(anchor):
        return set()
    identities = load_doc().get("identities") or {}
    return {aid for aid, row in identities.items() if isinstance(row, dict) and row.get("anchor") == anchor}


def same_agent(a: str | None, b: str | None, b_anchor: str | None = None) -> bool:
    """True when ``a`` and ``b`` are one agent: equal ids or ids on one live anchor."""
    if not a or not b:
        return False
    if a == b:
        return True
    identities = load_doc().get("identities") or {}
    anchor_a = (identities.get(a) or {}).get("anchor")
    anchor_b = b_anchor or (identities.get(b) or {}).get("anchor")
    return bool(anchor_a) and anchor_a == anchor_b and anchor_alive(anchor_a)


def _prune(identities: dict[str, Any], now: datetime) -> dict[str, Any]:
    alive: dict[str, bool] = {}
    kept = {}
    for aid, row in identities.items():
        if not isinstance(row, dict):
            continue
        anchor = row.get("anchor")
        if anchor not in alive:
            alive[anchor] = anchor_alive(anchor)
        if alive[anchor] and _fresh(row.get("last"), REGISTRY_TTL, now):
            kept[aid] = row
    return kept


def observe(*, reset: bool = False, subagent: bool = False, emit: bool = False) -> list[str]:
    """Register this identity on its anchor; on a reset return the one-line startup notice.

    A new identity on an anchor that already carries a live identity is a
    successor. ``reset`` marks an explicit reset hook; without it detection is
    lazy, except for Codex, where a new thread id on the same process may be
    a subagent thread (its SessionStart hook reports real resets). With
    ``emit`` the caller prints the notice; otherwise it waits for the next
    notices() surface.
    """
    anchor, provider = harness()
    if not anchor:
        return []
    agent_id, _, session_id, ident_provider = leases.identify_agent()
    expected = _PREFIX.get(provider or "")
    if not agent_id.startswith(expected or tuple(_PREFIX.values())):
        return []  # an id inherited from another harness never joins this process's family
    now = datetime.now(UTC)
    stamp = now.isoformat()
    with leases._lock("_coord"):
        doc = load_doc()
        identities = _prune(doc.get("identities") or {}, now)
        mine = identities.get(agent_id)
        if mine is not None and mine.get("anchor") != anchor:
            return []  # live on another process (e.g. resumed in another pane): never move it
        if mine is not None:
            mine["last"] = stamp
            pending = mine.pop("notice", None) if emit else None
            doc["identities"] = identities
            # Throttle registry writes: persist when a notice is consumed or a minute passed.
            if pending or not _fresh(mine.get("saved"), timedelta(minutes=1), now):
                mine["saved"] = stamp
                save_doc(doc)
            return [pending] if pending else []
        predecessors = sorted(
            (aid for aid, row in identities.items() if row.get("anchor") == anchor and aid != agent_id),
            key=lambda aid: identities[aid].get("last") or "",
        )
        identities[agent_id] = {
            "anchor": anchor, "session": session_id, "provider": provider or ident_provider,
            "first": stamp, "last": stamp, "saved": stamp,
        }
        doc["identities"] = identities
        codex = provider == "codex" or ident_provider == "codex_cli"
        line = None
        if predecessors and not subagent and (reset or not codex):
            line = _continuing_line(predecessors[-1], set(predecessors), doc)
            _note_peers(doc, agent_id, set(predecessors), predecessors[-1], now)
            if line and not emit:
                identities[agent_id]["notice"] = line
        save_doc(doc)
    return [line] if line and emit else []


# ---------------------------------------------------------------- notices

def _continuing_line(latest: str, predecessors: set[str], doc: dict[str, Any]) -> str | None:
    parts: list[str] = []
    holds: list[str] = []
    files: dict[str, int] = {}
    for project_id in leases.all_projects():
        try:
            live = leases.list_active(project_id, kinds=("hold", "file", "op"))
        except OSError:
            continue
        for lease in live:
            if lease.agent_id not in predecessors:
                continue
            if lease.kind == "hold":
                holds.append(project_id)
            elif lease.kind == "file":
                files[project_id] = files.get(project_id, 0) + 1
    if holds:
        parts.append("holds " + ",".join(sorted(set(holds))))
    if files:
        parts.append("leased files " + ",".join(f"{p}({n})" for p, n in sorted(files.items())))
    for row in doc.get("messages") or []:
        if row.get("state") == "closed":
            continue
        if row.get("from") in predecessors:
            if row.get("state") == "open":
                parts.append(f"awaiting ack from {row.get('to')} on {row.get('id')}")
            else:
                parts.append(f"ack {row.get('intent')} from {row.get('acked_by')} on {row.get('id')} to confirm")
        elif row.get("state") == "open" and _to_any(row.get("to"), predecessors, doc):
            parts.append(f"request {row.get('id')} from {row.get('from')} awaits your ack")
    if not parts:
        return None
    shown = parts[:4] + ([f"+{len(parts) - 4} more: st sessions inbox"] if len(parts) > 4 else [])
    return f"continuing {latest}: " + "; ".join(shown)


def _to_any(to: object, ids: set[str], doc: dict[str, Any]) -> bool:
    if not isinstance(to, str) or not to:
        return False
    if to in ids:
        return True
    identities = doc.get("identities") or {}
    return len(to) >= 13 and any(str((identities.get(i) or {}).get("session") or "").startswith(to) for i in ids)


def _note_peers(doc: dict[str, Any], successor: str, predecessors: set[str], latest: str, now: datetime) -> None:
    peers: set[str] = set()
    for row in doc.get("messages") or []:
        if row.get("state") == "closed":
            continue
        if row.get("from") in predecessors and row.get("to"):
            peers.add(str(row.get("acked_by") or row["to"]))
        elif _to_any(row.get("to"), predecessors, doc) and row.get("from"):
            peers.add(str(row["from"]))
    peers -= predecessors | {successor}
    notes = [n for n in doc.get("notes") or [] if _fresh(n.get("created"), NOTE_TTL, now)]
    for peer in sorted(peers):
        if any(n.get("to") == peer and n.get("about") == latest for n in notes):
            continue
        notes.append({
            "to": peer, "about": latest, "created": now.isoformat(),
            "text": f"{latest} context reset (now {successor}); resend full ask if pending",
        })
    doc["notes"] = notes


def pop_notes(is_me: Callable[[object], bool]) -> list[str]:
    """Peer notes addressed to me, surfaced once."""
    now = datetime.now(UTC)
    with leases._lock("_coord"):
        doc = load_doc()
        notes = doc.get("notes") or []
        mine = [n for n in notes if is_me(n.get("to"))]
        if not mine:
            return []
        doc["notes"] = [n for n in notes if n not in mine and _fresh(n.get("created"), NOTE_TTL, now)]
        save_doc(doc)
    return [str(n["text"]) for n in mine]
