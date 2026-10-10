"""Host-wide agent coordination on top of the lease store.

One identity (``leases.identify_agent``), one store (``~/.summitflow/leases``):
- file leases are auto-claimed by the edit hook (``st lease --hook``);
- repo marks: ``hold`` (declared coarse purpose, idle TTL) and ``op``
  (acceptance/deployment, fenced to the running process);
- a handshake ledger: request -> ack (intent) -> confirm, with one-line notices.

Output is silent without overlap. Minimal disclosure: sensitive holders render
as an opaque busy line; message text is one short neutral line.
"""

from __future__ import annotations

import json
import re
import subprocess
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import coord_lineage, leases

ACTIVE_WINDOW = timedelta(minutes=10)
UNACKED_AFTER = timedelta(minutes=10)
ACK_VALID_FOR = timedelta(hours=2)
LEDGER_TTL = timedelta(hours=24)
MAX_TEXT = 160
INTENTS = ("yes", "no")
_ETA = re.compile(r"eta:(\d{1,4})")


class CoordBlocked(Exception):
    """A repo operation conflicts with another live agent; message is one line."""


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
    if lease.kind in ("hold", "op"):
        return f"{project_id}: {lease.kind} {lease.purpose or '-'} by {lease.agent_id} since {since}"
    rel = lease.globs[0]
    if root is not None and rel.startswith(str(root) + "/"):
        rel = rel[len(str(root)) + 1:]
    return f"{project_id}: {rel} leased by {lease.agent_id} (idle {leases.idle_string(lease)})"


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


def guard(repo: Path, operation: str, *, paths: Sequence[str] = (), with_ack: str | None = None) -> None:
    """Refuse a repo-mutating or outward operation that another live agent would collide with.

    commit: blocked by any live op, or another agent's hold. acceptance: only by
    another agent's hold. Path overlap stays
    with the existing commit lease check. publish/rebuild/reconcile: also
    blocked by another agent's file lease touched within ACTIVE_WINDOW.
    An acked request (``--with-ack``) from that holder authorizes the operation.
    """
    resolved = project_for_path(repo)
    if resolved is None:
        return
    project_id, root = resolved
    coord_lineage.observe()
    _keep_alive(project_id)
    mine, anchor = leases.self_ids(), leases.my_anchor()
    # Acceptance only yields to an integration hold; concurrent runs are fine.
    kinds = {"commit": ("op", "hold"), "acceptance": ("hold",)}.get(operation, ("op", "hold", "file"))
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
    import os

    return os.getpid()


def edit_conflict(path: str) -> str | None:
    """Claim ``path`` for the current agent; return one blocking line on conflict."""
    target = Path(path).expanduser()
    resolved = project_for_path(target)
    if resolved is None:
        return None
    project_id, root = resolved
    real = str(target.resolve())
    marks = [m for m in leases.repo_marks(project_id) if m.kind == "op"]
    if marks and not _ignored(root, Path(real)):
        return f"{holder_line(project_id, marks[0], root)}; edits now invalidate it; work elsewhere, retry later"
    ok, holder = leases.claim(project_id, real, project_root=str(root))
    if ok or holder is None:
        _keep_alive(project_id)
        return None
    return (
        f"{holder_line(project_id, holder, root)}; ask: st sessions send {holder.agent_id} "
        '"<ask>" --delivery handshake, or st lease --take <path>'
    )


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
    """Key the hook on the event's session id: after a reset it is newer than any inherited env."""
    import os

    sid = str(payload.get("session_id") or payload.get("conversationId") or "")
    if not sid or os.environ.get("ST_SESSION_ID"):
        return
    provider = coord_lineage.harness()[1]
    if provider is None:
        codex = payload.get("tool_name") == "apply_patch" or "/.codex/" in str(payload.get("transcript_path") or "")
        provider = "codex" if codex else "claude_code"
    for key in _IDENTITY_ENV:
        os.environ.pop(key, None)
    os.environ[coord_lineage.session_env_for(provider) or "CLAUDE_CODE_SESSION_ID"] = sid


def session_start(payload: dict[str, Any]) -> str | None:
    """SessionStart/session_start hook: register the identity; one line if a reset left work open."""
    adopt_hook_identity(payload)
    source = str(payload.get("source") or payload.get("reason") or "")
    subagent = bool(payload.get("agent_id")) or source in ("resume", "compact")
    lines = coord_lineage.observe(reset=True, subagent=subagent, emit=True)
    return "\n".join(lines) or None


def run_hook(payload: dict[str, Any]) -> str | None:
    """Return one blocking message, or None to allow (fail-open on infra errors)."""
    adopt_hook_identity(payload)
    with suppress(Exception):  # lineage is best effort; never wedge an editor
        coord_lineage.observe()
    lines: list[str] = []
    for path in hook_paths(payload):
        try:
            conflict = edit_conflict(path)
        except Exception:  # the hook must never wedge an editor on infra faults
            conflict = None
        if conflict:
            lines.append("BLOCKED: " + conflict)
            break
    if not lines:
        return None
    lines.extend(notices())
    return "\n".join(lines)


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
    return kept


def _save_ledger(rows: list[dict[str, Any]]) -> None:
    """Replace the messages, keeping the lineage registry and peer notes (caller holds the lock)."""
    doc = coord_lineage.load_doc()
    doc["messages"] = rows
    coord_lineage.save_doc(doc)


def _clean_text(text: str) -> str:
    flat = " ".join(text.split())
    if not flat:
        raise ValueError("message text is empty")
    if len(flat) > MAX_TEXT:
        raise ValueError(f"message text exceeds {MAX_TEXT} chars; keep it to one neutral line")
    return flat


def _addresses(to: str, agent_id: str, session_id: str) -> bool:
    """Addressed to me: my id, a prefix of my session id, or any identity of my live harness process."""
    if not to:
        return False
    # Session prefixes need 13+ chars: UUIDv7 ids share their first 12 (a millisecond timestamp).
    if to == agent_id or (len(to) >= 13 and session_id.startswith(to)):
        return True
    family = coord_lineage.family_ids()
    if to in family:
        return True
    if len(to) < 13 or not family:
        return False
    identities = coord_lineage.load_doc().get("identities") or {}
    return any(str((identities.get(i) or {}).get("session") or "").startswith(to) for i in family)


def send(to: str, text: str, *, project: str | None = None) -> dict[str, Any]:
    """Record a request; an identical open request returns the existing row."""
    body = _clean_text(text)
    agent_id, _, session_id, _ = leases.identify_agent()
    now = datetime.now(UTC).isoformat()
    with leases._lock("_coord"):
        rows = _load_ledger()
        for row in rows:
            if row["from"] == agent_id and row["to"] == to and row["text"] == body and row["state"] == "open":
                return {**row, "duplicate": True}
        row = {
            "id": uuid.uuid4().hex[:6], "from": agent_id, "from_session": session_id, "to": to,
            "project": project, "text": body, "created": now, "state": "open",
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
            note=_clean_text(note) if note else None, acked_at=datetime.now(UTC).isoformat(),
            acked_by=agent_id, ack_seen=False,
        )
        _save_ledger(rows)
        return dict(row)


def confirm(message_id: str) -> dict[str, Any]:
    """Requester closes the exchange."""
    agent_id = leases.identify_agent()[0]
    with leases._lock("_coord"):
        rows = _load_ledger()
        row = _find(rows, message_id)
        if row["from"] not in leases.self_ids():
            raise ValueError(f"request {message_id} was not sent by {agent_id}")
        if row["state"] != "acked":
            raise ValueError(f"request {message_id} has no ack to confirm (state={row['state']})")
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
            elif row["state"] == "open" and not row.get("surfaced_at"):
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


def dirty_owner_line(project_id: str, root: Path) -> str | None:
    """Attribute dirty paths edited by other agents (from 24 h touch records)."""
    result = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        return None
    entries = [item[3:] for item in result.stdout.split("\0") if len(item) > 3]
    record = leases.touches(project_id)
    mine, anchor = leases.self_ids(), leases.my_anchor()
    foreign: list[str] = []
    for rel in entries:
        touch = record.get(str((root / rel).resolve())) or record.get(str(root / rel))
        if touch and touch.get("agent_id") not in mine and not (anchor and touch.get("anchor") == anchor):
            shown = _coarse(str(root / rel), root) if touch.get("sensitive") else rel
            foreign.append(f"{shown}<-{touch['agent_id']}({_age(touch['at'])})")
    if not foreign:
        return None
    return f"DIRTY-OWNER:{project_id}|" + ",".join(sorted(set(foreign))[:3])


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
    mine, anchor = leases.self_ids(), leases.my_anchor()
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


def dispatch_hook(payload: dict[str, Any]) -> tuple[str, str] | None:
    """Route one harness hook event: ("block", line) | ("context", line) | ("warn", line) | None."""
    event = str(payload.get("hook_event_name") or payload.get("event") or "")
    if event in ("SessionStart", "session_start"):
        line = session_start(payload)
        return ("context", line) if line else None
    if event in ("PostToolUse", "tool_result") and isinstance(payload.get("st_written"), list):
        adopt_hook_identity(payload)
        try:
            since = datetime.fromisoformat(str(payload.get("st_since")))
        except ValueError:
            return None
        line = shell_write_warning([str(p) for p in payload["st_written"]], since)
        return ("warn", line) if line else None
    message = run_hook(payload)
    return ("block", message) if message else None
