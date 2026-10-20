"""Host-wide agent coordination on top of the lease store.

One identity (``leases.identify_agent``), one store (``~/.summitflow/leases``):
- file leases are auto-claimed by the edit hook (``scripts/lib/lease-hook``); they are
  advisory: a collision warns, and st commit's writer-set guard prevents sweeps;
- writer sets: every session (or "unknown") that wrote a dirty path, from the
  edit hook and shell commands (bash-pre/post), kept until commit or revert;
- repo marks: ``hold`` (declared coarse purpose, idle TTL) and ``op``
  (acceptance/deployment, fenced to the running process);
- a handshake ledger: request -> ack (intent) -> confirm, with one-line notices; an
  eta ack whose minutes run out puts the request back to waiting on the recipient.

Output is silent without overlap. Minimal disclosure: sensitive holders render
as an opaque busy line; message text is short and neutral (long material goes in a brief file).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import coord_lineage, leases

ACTIVE_WINDOW = timedelta(minutes=10)
UNACKED_AFTER = timedelta(minutes=10)
ACK_VALID_FOR = timedelta(hours=2)
LEDGER_TTL = timedelta(hours=24)
MAX_TEXT = 500
# An ack reason stays one short line so the whole ACK notice fits a typed wake line (coord_wake.TYPE_MAX).
ACK_NOTE_MAX = 160
# Owner/fleet instructions to a live Codex thread ride the ledger; same bound as sanitized_instruction.
NATIVE_MAX_TEXT = 2000
INTENTS = ("yes", "no")
_ETA = re.compile(r"eta:(\d{1,4})")


class CoordBlocked(Exception):
    """A repo operation conflicts with another live agent; message is one line."""


# A command's --with-ack also covers the guarded steps it runs internally
# (its own commit and local acceptance), with the same holder fencing.
_COMMAND_ACK: ContextVar[str | None] = ContextVar("coord_command_ack", default=None)


@contextmanager
def acked(with_ack: str | None) -> Iterator[None]:
    """Let guards inside this command honor its ``--with-ack`` request id."""
    token = _COMMAND_ACK.set(with_ack or _COMMAND_ACK.get())
    try:
        yield
    finally:
        _COMMAND_ACK.reset(token)


# ---------------------------------------------------------------- resolution

def _git_toplevel(path: Path) -> Path | None:
    probe = path if path.is_dir() else path.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        result = subprocess.run(
            ["git", "-C", str(probe), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=False,
        )
    except OSError:
        return None
    top = result.stdout.strip() if isinstance(result.stdout, str) else ""
    return Path(top) if result.returncode == 0 and top else None


def project_for_path(path: str | Path) -> tuple[str, Path] | None:
    """Store key and root for the checkout that owns ``path`` (not the caller's cwd)."""
    target = Path(path).expanduser()
    top = _git_toplevel(target)
    if top is None:
        return None
    from .execution_context import resolve_checkout_project_id

    return (resolve_checkout_project_id(top) or top.name), top


def _ignored(root: Path, path: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "-q", str(path)],
        capture_output=True, check=False,
    )
    return result.returncode == 0


# ---------------------------------------------------------------- rendering

def _age(stamp: str, now: datetime | None = None) -> str:
    try:
        then = datetime.fromisoformat(stamp)
    except ValueError:
        return "?"
    secs = int(((now or datetime.now(UTC)) - then).total_seconds())
    return f"{secs}s" if secs < 60 else f"{secs // 60}m" if secs < 3600 else f"{secs // 3600}h"


def _coarse(path: str, root: Path | None) -> str:
    if root is not None:
        try:
            rel = Path(path.removesuffix("/**")).relative_to(root)
        except ValueError:
            rel = None
        if rel is not None:
            return f"{rel.parts[0]}/**" if rel.parts else "**"
    return "**"


def holder_line(project_id: str, lease: leases.Lease, root: Path | None = None) -> str:
    """One line naming who holds what; opaque for sensitive holders."""
    since = _age(lease.acquired_at)
    if lease.sensitive:
        return f"{project_id}: busy ({_coarse(lease.globs[0], root)}) since {since} · contact {lease.agent_id}"
    from .coordinators import conflict_suffix

    if lease.kind in ("hold", "op"):
        return f"{project_id}: {lease.kind} {lease.purpose or '-'} by {lease.agent_id} since {since}{conflict_suffix(lease)}"
    rel = lease.globs[0]
    if root is not None and rel.startswith(str(root) + "/"):
        rel = rel[len(str(root)) + 1:]
    return f"{project_id}: {rel} leased by {lease.agent_id} (idle {leases.idle_string(lease)}){conflict_suffix(lease)}"


# ---------------------------------------------------------------- repo marks

@contextmanager
def op_lease(repo: Path, purpose: str) -> Iterator[None]:
    """Hold an op lease for the life of this process's repo operation (best effort)."""
    resolved = project_for_path(repo)
    mark = None
    if resolved is not None:
        try:
            mark = leases.acquire_mark(resolved[0], str(resolved[1]), "op", purpose)
        except OSError:
            mark = None
    try:
        yield
    finally:
        if mark is not None and resolved is not None:
            with suppress(OSError):
                leases.release_mark(resolved[0], mark.lease_id)


def guard(repo: Path, operation: str, *, with_ack: str | None = None) -> None:
    """Refuse a repo-mutating or outward operation that another live agent would collide with.

    commit, rebuild and publish (which ship an accepted commit, not the working
    tree): blocked by any live op, or another agent's hold. acceptance: only by
    another agent's hold. reconcile (syncs working trees): also blocked by another
    agent's file lease touched within ACTIVE_WINDOW. An acked request
    (``--with-ack``) from that holder authorizes the operation.
    """
    resolved = project_for_path(repo)
    if resolved is None:
        return
    project_id, root = resolved
    with_ack = with_ack or _COMMAND_ACK.get()
    coord_lineage.observe()
    _keep_alive(project_id)
    mine, anchor = leases.session_ids()  # my harness process's child threads are not other agents
    # Acceptance only yields to an integration hold; concurrent runs are fine.
    kinds = {"commit": ("op", "hold"), "rebuild": ("op", "hold"), "publish": ("op", "hold"),
             "acceptance": ("hold",)}.get(operation, ("op", "hold", "file"))
    now = datetime.now(UTC)
    for lease in leases.list_active(project_id, kinds=kinds):
        if lease.kind == "op":
            if lease.pid == _own_pid():
                continue
        elif leases.is_mine(lease, mine, anchor):
            continue
        elif lease.kind == "file":
            try:
                if now - datetime.fromisoformat(lease.last_heartbeat) > ACTIVE_WINDOW:
                    continue
            except ValueError:
                continue
        if lease.kind != "op" and with_ack and ack_authorizes(with_ack, lease, project_id):
            continue
        hint = (
            "wait for it to finish"
            if lease.kind == "op"
            else f'request handoff: st sessions send {lease.agent_id} "<ask>" --delivery handshake, then rerun with --with-ack <id>'
        )
        raise CoordBlocked(f"{holder_line(project_id, lease, root)}; {operation} refused; {hint}")


def _keep_alive(project_id: str) -> None:
    """Working in a repo (edits, guarded operations) keeps this agent's holds live."""
    with suppress(OSError):
        leases.heartbeat(project_id)


def _own_pid() -> int:
    return os.getpid()


def _op_block(project_id: str, root: Path, real: str) -> str | None:
    """One line when a live op (acceptance/deployment) would be invalidated by editing ``real``."""
    marks = [m for m in leases.repo_marks(project_id) if m.kind == "op"]
    if marks and not _ignored(root, Path(real)):
        return f"{holder_line(project_id, marks[0], root)}; edits now invalidate it; work elsewhere, retry later"
    return None


def claim_edit(path: str, *, check_op: bool = True) -> tuple[str, str] | None:
    """Claim ``path`` for the current agent: ("block", line) under a live op, ("warn", line) on a foreign lease.

    File leases are advisory: on a foreign lease the path is still leased and
    recorded, because the edit goes ahead; st commit then refuses to sweep it.
    """
    target = Path(path).expanduser()
    resolved = project_for_path(target)
    if resolved is None:
        return None
    project_id, root = resolved
    real = str(target.resolve())
    blocked = _op_block(project_id, root, real) if check_op else None
    if blocked:
        return "block", blocked
    ok, holder = leases.claim(project_id, real, project_root=str(root))
    _keep_alive(project_id)
    if ok or holder is None:
        return None
    return "warn", (
        f"{holder_line(project_id, holder, root)}; edit allowed, both of you are now its writers and "
        f'st commit refuses to sweep it; tell them: st sessions send {holder.agent_id} "<what changed>" --delivery handshake'
    )


def edit_conflict(path: str) -> str | None:
    """Claim ``path`` as the edit hook does; return one line on a live op or a foreign lease."""
    found = claim_edit(path)
    return found[1] if found else None


# ---------------------------------------------------------------- hook

_PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$|^\*\*\* Move to: (.+)$", re.MULTILINE)


def hook_paths(payload: dict[str, Any]) -> list[str]:
    """Edited paths from a Claude Code or Codex PreToolUse payload."""
    tool_input = payload.get("tool_input") or {}
    cwd = Path(str(payload.get("cwd") or "."))
    found: list[str] = []
    if isinstance(tool_input, dict):
        for key in ("file_path", "notebook_path", "path"):
            value = tool_input.get(key)
            if isinstance(value, str) and value:
                found.append(value)
        if not found:
            for value in tool_input.values():
                if isinstance(value, str):
                    found.extend(a or b for a, b in _PATCH_FILE.findall(value))
    elif isinstance(tool_input, str):
        found.extend(a or b for a, b in _PATCH_FILE.findall(tool_input))
    return [str(p if Path(p).is_absolute() else cwd / p) for p in (s.strip() for s in found) if p]


_IDENTITY_ENV = ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID", "CODEX_THREAD_ID",
                 "PI_SESSION_ID", "ANTIGRAVITY_CONVERSATION_ID")


def adopt_hook_identity(payload: dict[str, Any]) -> None:
    """Use the event's native identity: Codex worker agent_id, otherwise session_id."""
    sid = str(payload.get("session_id") or payload.get("conversationId") or "")
    st_sid = os.environ.get("ST_SESSION_ID") or ""
    if not sid or (st_sid and not st_sid.startswith(leases.ROOT_HANDLE_PREFIX)):
        return
    provider = coord_lineage.harness()[1]
    if provider is None:
        codex = payload.get("tool_name") == "apply_patch" or "/.codex/" in str(payload.get("transcript_path") or "")
        provider = "codex" if codex else "claude_code"
    # Codex worker events carry the parent's session_id and their own native agent_id.
    if provider == "codex" and payload.get("agent_id"):
        sid = str(payload["agent_id"])
    for key in _IDENTITY_ENV:
        os.environ.pop(key, None)
    os.environ[coord_lineage.session_env_for(provider) or "CLAUDE_CODE_SESSION_ID"] = sid


def session_start(payload: dict[str, Any]) -> str | None:
    """SessionStart/session_start hook: register the identity; one line if a reset left work open."""
    adopt_hook_identity(payload)
    source = str(payload.get("source") or payload.get("reason") or "")
    subagent = bool(payload.get("agent_id")) or source in ("resume", "compact")
    lines = coord_lineage.observe(reset=True, subagent=subagent, emit=True)
    if not payload.get("agent_id"):
        with suppress(Exception):
            _mark_main_thread()
    return "\n".join(lines) or None


def _mark_main_thread() -> None:
    """Record this identity as its harness process's main thread (SessionStart never fires for child threads)."""
    agent_id = leases.identify_agent()[0]
    with leases._lock("_coord"):
        doc = coord_lineage.load_doc()
        row = (doc.get("identities") or {}).get(agent_id)
        if isinstance(row, dict) and not row.get("main"):
            row["main"] = True
            coord_lineage.save_doc(doc)


def run_hook(payload: dict[str, Any]) -> str | None:
    """Return one "BLOCKED: " (live op) or "WARNING: " (foreign lease) message, or None (fail-open on infra errors)."""
    adopt_hook_identity(payload)
    with suppress(Exception):  # lineage is best effort; never wedge an editor
        coord_lineage.observe()
    paths = hook_paths(payload)
    for path in paths:  # a blocked edit never happens, so nothing is claimed or recorded before this pass
        try:
            target = Path(path).expanduser()
            resolved = project_for_path(target)
            blocked = _op_block(*resolved, str(target.resolve())) if resolved else None
        except Exception:  # the hook must never wedge an editor on infra faults
            blocked = None
        if blocked:
            return "\n".join(["BLOCKED: " + blocked, *notices()])
    lines: list[str] = []
    for path in paths:
        try:
            found = claim_edit(path, check_op=False)
        except Exception:
            found = None
        if found:
            lines.append("WARNING: " + found[1])
    return "\n".join(lines) or None


# ---------------------------------------------------------------- ledger

def _ledger_path() -> Path:
    return leases.LEASES_DIR / "_coord.json"


def _load_ledger() -> list[dict[str, Any]]:
    path = _ledger_path()
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    rows = data.get("messages", []) if isinstance(data, dict) else []
    now = datetime.now(UTC)
    kept = []
    for row in rows:
        try:
            if now - datetime.fromisoformat(row["created"]) <= LEDGER_TTL:
                kept.append(row)
        except (KeyError, ValueError, TypeError):
            continue
        with suppress(KeyError, ValueError, TypeError):
            _reopen_lapsed_eta(row, now)
    return kept


def _reopen_lapsed_eta(row: dict[str, Any], now: datetime) -> None:
    """An eta ack whose minutes ran out is waiting on the recipient again (open, intent stays eta)."""
    if (row["state"] == "acked" and row["intent"] == "eta" and row.get("eta_min") is not None
            and now >= datetime.fromisoformat(row["acked_at"]) + timedelta(minutes=int(row["eta_min"]))):
        row["state"] = "open"


def _save_ledger(rows: list[dict[str, Any]]) -> None:
    """Replace the messages, keeping the lineage registry and peer notes (caller holds the lock)."""
    doc = coord_lineage.load_doc()
    doc["messages"] = rows
    coord_lineage.save_doc(doc)


def _clean_text(text: str, limit: int = MAX_TEXT) -> str:
    flat = " ".join(text.split())
    if not flat:
        raise ValueError("message text is empty")
    if len(flat) > limit:
        raise ValueError(f"message text exceeds {limit} chars; put long material in a brief file and send its path")
    return flat


def _addresses(to: str, agent_id: str, session_id: str) -> bool:
    """My identity or main-thread predecessors; workers keep their own inboxes."""
    if not to:
        return False
    # Session prefixes need 13+ chars: UUIDv7 ids share their first 12 (a millisecond timestamp).
    if to == agent_id or (len(to) >= 13 and session_id.startswith(to)):
        return True
    family = leases.self_ids()
    if to in family:
        return True
    if len(to) < 13 or not family:
        return False
    identities = coord_lineage.load_doc().get("identities") or {}
    return any(str((identities.get(i) or {}).get("session") or "").startswith(to) for i in family)


def known_target(to: str) -> bool:
    """True when ``to`` names a registered identity: its exact id or a 13+ char session prefix.

    The ledger matches recipients only by these forms, so a title, pane or
    label (e.g. ``neri-bc``) can never be acked and would sit unseen.
    """
    identities = coord_lineage.load_doc().get("identities") or {}
    if to in identities:
        return True
    return len(to) >= 13 and any(str((row or {}).get("session") or "").startswith(to) for row in identities.values())


def live_agents() -> list[str]:
    """Registered identities whose harness process is still alive."""
    identities = coord_lineage.load_doc().get("identities") or {}
    return sorted(aid for aid, row in identities.items()
                  if isinstance(row, dict) and coord_lineage.anchor_alive(row.get("anchor")))


def send(to: str, text: str, *, project: str | None = None, limit: int = MAX_TEXT,
         source_key: str | None = None) -> dict[str, Any]:
    """Record a request; an identical open request, or any request with the same source key, returns the existing row.

    The source key is the sender's stable revision for one instruction: a retry
    or fallback with that key never records a second request, whatever its state.
    """
    body = _clean_text(text, limit)
    agent_id, _, session_id, _ = leases.identify_agent()
    now = datetime.now(UTC).isoformat()
    with leases._lock("_coord"):
        rows = _load_ledger()
        for row in rows:
            if row["from"] != agent_id or row["to"] != to:
                continue
            if (source_key and row.get("source_key") == source_key) or (row["text"] == body and row["state"] == "open"):
                return {**row, "duplicate": True}
        row = {
            "id": uuid.uuid4().hex[:6], "from": agent_id, "from_session": session_id, "to": to,
            "project": project, "source_key": source_key, "text": body, "created": now, "state": "open",
            "intent": None, "eta_min": None, "note": None, "acked_at": None,
            "closed_at": None, "surfaced_at": None, "ack_seen": False,
        }
        rows.append(row)
        _save_ledger(rows)
    return row


def ack(message_id: str, intent: str, note: str | None = None) -> dict[str, Any]:
    """Recipient states intent: yes | no | eta:<minutes>."""
    eta = _ETA.fullmatch(intent)
    if intent not in INTENTS and not eta:
        raise ValueError("intent must be yes, no or eta:<minutes>")
    if intent == "no" and not note:
        raise ValueError("a 'no' ack needs a short reason")
    agent_id, _, session_id, _ = leases.identify_agent()
    with leases._lock("_coord"):
        rows = _load_ledger()
        row = _find(rows, message_id)
        if not _addresses(row["to"], agent_id, session_id):
            raise ValueError(f"request {message_id} is not addressed to {agent_id}")
        if row["state"] == "closed":
            raise ValueError(f"request {message_id} is already closed")
        row.update(
            state="acked", intent="eta" if eta else intent, eta_min=int(eta.group(1)) if eta else None,
            note=_clean_text(note, ACK_NOTE_MAX) if note else None, acked_at=datetime.now(UTC).isoformat(),
            acked_by=agent_id, ack_seen=False,
        )
        _save_ledger(rows)
        return dict(row)


def confirm(message_id: str, *, withdraw: bool = False) -> dict[str, Any]:
    """Requester closes the exchange; ``withdraw`` closes one nobody acked (it authorizes nothing)."""
    agent_id = leases.identify_agent()[0]
    with leases._lock("_coord"):
        rows = _load_ledger()
        row = _find(rows, message_id)
        if row["from"] not in leases.self_ids():
            raise ValueError(f"request {message_id} was not sent by {agent_id}")
        if withdraw:
            if row["state"] != "open":
                raise ValueError(f"request {message_id} is {row['state']}; only an unacked request can be withdrawn")
            row["withdrawn"] = True
        elif row["state"] != "acked":
            raise ValueError(f"request {message_id} has no ack to confirm (state={row['state']}); "
                             f"to drop it: st sessions confirm {message_id} --withdraw")
        row.update(state="closed", closed_at=datetime.now(UTC).isoformat(), ack_seen=True)
        _save_ledger(rows)
        return dict(row)


def _find(rows: list[dict[str, Any]], message_id: str) -> dict[str, Any]:
    for row in rows:
        if row["id"] == message_id:
            return row
    raise ValueError(f"unknown request {message_id}")


def ack_authorizes(message_id: str, holder: leases.Lease, project_id: str) -> bool:
    """A yes-ack from this holder, for this project, younger than ACK_VALID_FOR."""
    mine = leases.self_ids()
    with leases._lock("_coord"):
        rows = _load_ledger()
    for row in rows:
        if row["id"] != message_id or row["from"] not in mine or row.get("intent") != "yes":
            continue
        if not coord_lineage.same_agent(row.get("acked_by"), holder.agent_id, holder.anchor) or row.get("project") not in (None, project_id):
            return False
        try:
            return datetime.now(UTC) - datetime.fromisoformat(row["acked_at"]) <= ACK_VALID_FOR
        except (TypeError, ValueError):
            return False
    return False


def surfaced(row: dict[str, Any]) -> bool:
    """True once the recipient's own hook or watcher has shown it this request (content-free seen state)."""
    from . import coord_wake

    return f"{row['id']}:req" in coord_wake.load_seen(str(row["to"]))


def inbox() -> list[dict[str, Any]]:
    """Requests awaiting my ack, and acks awaiting my confirm."""
    agent_id, _, session_id, _ = leases.identify_agent()
    mine = leases.self_ids()
    with leases._lock("_coord"):
        rows = _load_ledger()
    return [
        row for row in rows
        if (row["state"] == "open" and _addresses(row["to"], agent_id, session_id))
        or (row["state"] == "acked" and row["from"] in mine)
        or (row["state"] == "open" and row["from"] in mine)
    ]


def notices() -> list[str]:
    """One line per actionable item; unacked requests, resets and peer notes surface once."""
    agent_id, _, session_id, _ = leases.identify_agent()
    out: list[str] = coord_lineage.observe(emit=True)
    out.extend(coord_lineage.pop_notes(lambda to: _addresses(str(to or ""), agent_id, session_id)))
    mine = leases.self_ids()
    now = datetime.now(UTC)
    with leases._lock("_coord"):
        rows = _load_ledger()
        changed = False
        to_me = [r for r in rows if r["state"] == "open" and _addresses(r["to"], agent_id, session_id)]
        if to_me:
            ids = ",".join(r["id"] for r in to_me[:3])
            out.append(f"INBOX {len(to_me)} request(s) {ids} awaiting your ack: st sessions inbox")
        for row in rows:
            if row["from"] not in mine:
                continue
            if row["state"] == "acked" and not row.get("ack_seen"):
                intent = row["intent"] + (f" {row['eta_min']}m" if row.get("eta_min") else "")
                out.append(f"ACK {row['id']} {intent} from {row.get('acked_by')}; close: st sessions confirm {row['id']}")
                row["ack_seen"] = True
                changed = True
            elif row["state"] == "open" and not row.get("surfaced_at") and not row.get("intent"):
                if now - datetime.fromisoformat(row["created"]) >= UNACKED_AFTER:
                    out.append(f"UNACKED {row['id']} -> {row['to']} ({_age(row['created'], now)}); escalate or route around")
                    row["surfaced_at"] = now.isoformat()
                    changed = True
        if changed:
            _save_ledger(rows)
    return out


# ---------------------------------------------------------------- awareness

def system_lines() -> list[str]:
    """One line per live hold/op/file lease across projects; empty when idle."""
    out: list[str] = []
    for project_id in leases.all_projects():
        try:
            live = leases.list_active(project_id, kinds=("op", "hold", "file"))
        except OSError:
            continue
        for lease in live:
            out.append(holder_line(project_id, lease))
    return out


def dirty_paths(root: Path) -> list[str] | None:
    """Repo-relative dirty paths, rename sources included (they are deletions); None when git fails."""
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        return None
    items = iter(result.stdout.split("\0"))
    out: list[str] = []
    for item in items:
        if len(item) < 4:
            continue
        out.append(item[3:])
        if item[0] in "RC":
            source = next(items, "")
            if item[0] == "R" and source:
                out.append(source)
    return out


def foreign_writers(project_id: str, root: Path, rels: Sequence[str]) -> dict[str, list[dict]]:
    """Repo-relative path -> writer entries that are not my session (unknown writers included)."""
    record = leases.writers(project_id)
    if not record:
        return {}
    mine, anchor = leases.session_ids()
    out: dict[str, list[dict]] = {}
    for rel in rels:
        entries = record.get(str((root / rel).resolve())) or record.get(str(root / rel)) or []
        foreign = [e for e in entries if not leases.is_own_writer(e, mine, anchor)]
        if foreign:
            out[rel] = foreign
    return out


def dirty_owner_line(project_id: str, root: Path) -> str | None:
    """Attribute dirty paths written by other sessions or unknown writers (from writer sets)."""
    entries = dirty_paths(root)
    if not entries:
        return None
    foreign: list[str] = []
    for rel, writers in foreign_writers(project_id, root, entries).items():
        for entry in writers:
            shown = _coarse(str(root / rel), root) if entry.get("sensitive") else rel
            foreign.append(f"{shown}<-{leases.writer_label(entry)}({_age(str(entry.get('at')))})")
    if not foreign:
        return None
    return f"DIRTY-OWNER:{project_id}|" + ",".join(sorted(set(foreign))[:3])


def record_shell_writes(
    written: Sequence[str],
    since: datetime,
    *,
    other: Sequence[str] = (),
    background: bool = False,
    dirty: Sequence[str] | None = None,
) -> None:
    """Join the writer sets of paths a shell command wrote (deletions included).

    ``written`` is from the command's cwd repo and is recorded for this
    session, or as unknown for a background command whose writes continue
    after the hook. ``other`` (writes in other repos the command named) is
    recorded as unknown. ``dirty`` is the cwd repo's whole dirty set after the
    command: writer sets of paths no longer dirty there are dropped.
    """
    dirty_set = {os.path.realpath(p) for p in dirty} if dirty is not None else None
    groups: dict[str, tuple[Path, list[str], str | None]] = {}
    for paths, reason in ((written, "background" if background else None), (other, "other-repo")):
        for path in paths:
            resolved = project_for_path(path)
            if resolved is None:
                continue
            key = f"{resolved[0]}\0{reason or ''}"
            groups.setdefault(key, (resolved[1], [], reason))[1].append(os.path.realpath(path))
    pruned: set[str] = set()
    for key, (root, paths, reason) in groups.items():
        project_id = key.split("\0", 1)[0]
        prune = dirty_set is not None and reason != "other-repo" and project_id not in pruned
        leases.record_writes(project_id, paths, since=since, unknown=reason,
                             dirty=dirty_set if prune else None, root=str(root.resolve()) if prune else None)
        if prune:
            pruned.add(project_id)


def shell_write_warning(paths: Sequence[str], since: datetime) -> str | None:
    """One line when a shell command just wrote a path another agent leased before it started.

    Warn only: the write already happened, and a lease refreshed during the
    command means its holder edited concurrently, not that this shell did.
    """
    by_repo: dict[str, tuple[Path, list[str]]] = {}
    for path in paths:
        resolved = project_for_path(path)
        if resolved is not None:
            by_repo.setdefault(resolved[0], (resolved[1], []))[1].append(str(Path(path).resolve()))
    mine, anchor = leases.session_ids()
    for project_id, (root, written) in by_repo.items():
        for lease in leases.list_active(project_id, kinds=("file",)):
            if leases.is_mine(lease, mine, anchor):
                continue
            try:
                if datetime.fromisoformat(lease.last_heartbeat) >= since:
                    continue
            except ValueError:
                continue
            if any(lease.matches(p) for p in written):
                return (
                    f"OVERLAP: this shell command wrote {holder_line(project_id, lease, root)}; "
                    f'tell them: st sessions send {lease.agent_id} "<what changed>" --delivery handshake'
                )
    return None


GITHUB_PAT_DENIED = "Resource not accessible by personal access token"
_SHELL_SEPARATORS = frozenset(";&|()\n$`")
_COMMAND_PREFIXES = frozenset({"env", "command", "exec", "time", "timeout", "nice", "nohup", "sudo", "xargs"})
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")


def _invokes_github(command: str) -> bool:
    """True when a shell command runs ``gh`` or ``git push``, not when it merely quotes them."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
    lexer.whitespace, lexer.whitespace_split = " \t\r", True
    try:
        tokens = list(lexer)
    except ValueError:
        return False
    at_start, git_args, skip_value = True, False, False
    for token in tokens:
        if token and set(token) <= _SHELL_SEPARATORS:
            at_start, git_args = True, False
            continue
        if at_start:
            name = token.rsplit("/", 1)[-1]
            if _ASSIGNMENT.match(token) or name in _COMMAND_PREFIXES or token.startswith("-") or token.isdigit():
                continue
            if name == "gh":
                return True
            at_start, git_args, skip_value = False, name == "git", False
            continue
        if git_args:
            if skip_value:
                skip_value = False
            elif token in ("-C", "-c"):
                skip_value = True
            elif not token.startswith("-"):
                if token == "push":
                    return True
                git_args = False
    return False


def github_pat_denied_event(payload: dict[str, Any]) -> str | None:
    """Hook event name when a shell tool that ran ``gh``/``git push`` failed with GitHub's fine-grained-PAT 403.

    Only the tool's error channel counts: Claude ``tool_response.stderr`` (PostToolUse) or ``error``
    (PostToolUseFailure); Codex reports one combined result string, so the command check carries it.
    """
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(command, list):
        argv = [str(part) for part in command]
        commands = [shlex.join(argv), *argv[-1:]]  # ["bash", "-lc", "<script>"] carries the script last
    else:
        commands = [command] if isinstance(command, str) else []
    if not any(_invokes_github(text) for text in commands):
        return None
    response = payload.get("tool_response")
    channels = [payload.get("error"), response.get("stderr") if isinstance(response, dict) else response]
    if not any(isinstance(text, str) and GITHUB_PAT_DENIED in text for text in channels):
        return None
    return str(payload.get("hook_event_name") or "PostToolUse")


def dispatch_hook(payload: dict[str, Any]) -> tuple[str, str] | None:
    """Route one harness hook event: ("block", line) | ("context", line) | ("warn", line) | None.

    An edit's foreign-lease WARNING is "context": the edit proceeds and the model sees the line.
    """
    event = str(payload.get("hook_event_name") or payload.get("event") or "")
    if event in ("SessionStart", "session_start"):
        line = session_start(payload)
        return ("context", line) if line else None
    if event in ("PostToolUse", "PostToolUseFailure", "tool_result") and isinstance(payload.get("st_written"), list):
        adopt_hook_identity(payload)
        try:
            since = datetime.fromisoformat(str(payload.get("st_since")))
        except ValueError:
            return None
        written = [str(p) for p in payload["st_written"]]
        line = shell_write_warning(written, since)
        with suppress(Exception):  # attribution is best effort; never fail the shell hook
            dirty = payload.get("st_dirty")
            record_shell_writes(
                written, since, other=[str(p) for p in payload.get("st_other") or []],
                background=bool(payload.get("st_background")),
                dirty=[str(p) for p in dirty] if isinstance(dirty, list) else None,
            )
        return ("warn", line) if line else None
    message = run_hook(payload)
    if not message:
        return None
    return ("block" if message.startswith("BLOCKED: ") else "context", message)
