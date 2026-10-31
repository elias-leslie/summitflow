"""Coordination inbox wakes through Tether's gated delivery queue.

Since Tether API 16 (tether docs/api-v1.md "Deliveries") the inbox no longer
types into panes or wakes harnesses on its own when it can name the
recipient's Aico window: it queues one content-free line on that window's
delivery queue (``POST /v1/sessions/<widget>/deliveries``), and Tether pastes
it once the agent is idle, nobody is typing and the input is empty, hands it to
a native puller, or gives an Agent Hub chat a turn. The agent's own turn hook
(scripts/lib/coord_inbox.py) still shows the content. The line comes from
typed values only (counts and agent ids), never request or reply text.

One source per recipient (``coord:<agent id>``) coalesces: a newer line
replaces an undelivered one, so the line always summarises everything the
recipient has waiting. What was queued for which inbox item is kept in the
recipient's content-free woke state (cli.lib.coord_wake), so the recipient's
own watcher does not wake it a second time for the same item.

Unresolved recipients, shells, agy and an older Tether keep today's path:
every function here answers None and the caller carries on as before.
"""

from __future__ import annotations

import hashlib
import re
import time
from http.client import HTTPException
from typing import Any
from urllib.parse import quote

from . import coord, coord_lineage, coord_wake, coordinators, leases

DELIVERY_API = 16  # POST /v1/sessions/:id/deliveries, GET /v1/deliveries/:id
NUDGE_API = 17  # POST /v1/waits/check
SOURCE_PREFIX = "coord:"
_TIMEOUT = 2.0
_NUDGE_TIMEOUT = 0.5
# What a line may name: agent ids (cc:1c7a9f, codex:019a…, pi:…, st:…, with @host for a host agent).
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,15}:[A-Za-z0-9_.-]{1,64}(@[a-z0-9][a-z0-9-]{0,31})?")
_WIDGET = re.compile(r"[0-9a-f]{8}")
_NAMED = 3  # senders named on one line before "+N"
LOOK = "st sessions inbox"


_VERSION_TTL = 60.0  # long-lived callers (the API, a 6 h watcher) see a Tether upgrade or restart
_version: tuple[float, int | None] | None = None


def api_version() -> int | None:
    """The local Tether's apiVersion, or None when it does not answer (re-read after a minute)."""
    global _version
    from app.services import tether

    now = time.monotonic()
    if _version is not None and now - _version[0] < _VERSION_TTL:
        return _version[1]
    try:
        status, body = tether.request("GET", "/v1/version", timeout=0.5, max_bytes=4096)
        version = body.get("apiVersion") if status == 200 and isinstance(body, dict) else None
    except (OSError, ValueError, HTTPException):
        version = None
    _version = (now, version if isinstance(version, int) else None)
    return _version[1]


def enabled() -> bool:
    version = api_version()
    return version is not None and version >= DELIVERY_API


# ---------------------------------------------------------------- recipients

def _identity(agent_id: str) -> tuple[str, dict[str, Any]] | None:
    """(agent id, identity row) a ledger address names: an exact id or a 13+ char session prefix."""
    identities = coord_lineage.load_doc().get("identities") or {}
    row = identities.get(agent_id)
    if isinstance(row, dict):
        return agent_id, row
    if len(agent_id) >= 13:
        for aid, other in identities.items():
            if isinstance(other, dict) and str(other.get("session") or "").startswith(agent_id):
                return aid, other
    return None


def widget_for(to: str) -> str | None:
    """The Aico window (Tether session id) a local recipient's live harness runs in, or None.

    agy has no delivery in Tether (409) and keeps its own path; an address on
    another machine (``<window>@<host>``) is coord_remote's.
    """
    if not to or "@" in to or to.startswith("agy:"):
        return None
    found = _identity(to)
    if found is None:
        return None
    widget = coordinators.widget_for_anchor(found[1].get("anchor"))
    return widget if widget and _WIDGET.fullmatch(widget) else None


# ---------------------------------------------------------------- the line

def _names(ids: list[str]) -> str:
    shown = list(dict.fromkeys(i for i in ids if _ID.fullmatch(i)))
    if not shown:
        return "another agent"
    extra = len(shown) - _NAMED
    return ", ".join(shown[:_NAMED]) + (f" +{extra}" if extra > 0 else "")


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def waiting(to: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(open requests to ``to``, acks of its requests it has not been shown) in the ledger."""
    found = _identity(to)
    agent_id = found[0] if found else to
    session = str((found[1] if found else {}).get("session") or "")
    seen = coord_wake.load_seen(agent_id)

    def addressed(row_to: str) -> bool:
        return row_to in (agent_id, to) or (len(row_to) >= 13 and bool(session) and session.startswith(row_to))

    with leases._lock("_coord"):
        rows = coord._load_ledger()
    requests = [r for r in rows if r["state"] == "open" and addressed(str(r["to"])) and r["from"] != agent_id]
    acks = [r for r in rows if r["state"] == "acked" and r["from"] in (agent_id, to)
            and f"{r['id']}:ack:{r.get('acked_at')}" not in seen]
    return requests, acks


def summary(to: str, *, memory: bool = False) -> str | None:
    """``[Message] 2 requests from cc:1c7a9f, codex:019a2b · 1 ack from cc:65b53f · st sessions inbox``."""
    requests, acks = waiting(to)
    parts = []
    if requests:
        parts.append(f"{_plural(len(requests), 'request')} from {_names([str(r['from']) for r in requests])}")
    if acks:
        parts.append(f"{_plural(len(acks), 'ack')} from {_names([str(r.get('acked_by') or '') for r in acks])}")
    if memory:
        parts.append("a memory notice for this pane")
    if not parts:
        return None
    return "[Message] " + " · ".join(parts) + f" · {LOOK}"


# ---------------------------------------------------------------- queueing

def post(widget: str, source: str, line: str) -> dict[str, Any] | None:
    """Queue ``line`` on ``widget``'s delivery queue: Tether's record, or None when it was not taken.

    The hub forwards a session on another host to that host's Tether; an older
    one answers 404 and the caller keeps its own path.
    """
    from app.services import tether

    try:
        status, body = tether.request("POST", f"/v1/sessions/{quote(widget, safe='')}/deliveries",
                                      {"source": source, "line": line}, timeout=_TIMEOUT)
    except (OSError, ValueError, HTTPException):
        return None
    return body if status in (200, 201) and isinstance(body, dict) and body.get("id") else None


def state(delivery_id: str) -> dict[str, Any] | None:
    """``GET /v1/deliveries/:id``: {state: queued|delivered|dropped, via, deliveredAt, ...}, or None."""
    from app.services import tether

    if not re.fullmatch(r"[0-9a-f]{12}", delivery_id or ""):
        return None
    try:
        status, body = tether.request("GET", f"/v1/deliveries/{delivery_id}", timeout=_TIMEOUT)
    except (OSError, ValueError, HTTPException):
        return None
    return body if status == 200 and isinstance(body, dict) else None


def memory_key(text: str) -> str:
    return "mem:" + hashlib.sha256(text.encode()).hexdigest()[:16]


def wake(to: str, keys: list[str] | tuple[str, ...] = (), *, memory: str | None = None) -> dict[str, Any] | None:
    """Queue the recipient's ``[Message]`` line through Tether and record ``keys`` as woken.

    ``memory`` is a memory notice's text for that recipient (only its key is
    kept). Returns ``{delivery, widget, line}`` or None when the recipient keeps
    today's path (older Tether, no resolvable window, shell or agy, refused).
    """
    if not enabled():
        return None
    widget = widget_for(to)
    if widget is None:
        return None
    found = _identity(to)
    agent_id = found[0] if found else to
    line = summary(agent_id, memory=memory is not None)
    if line is None:
        return None
    delivery = post(widget, SOURCE_PREFIX + agent_id, line)
    if delivery is None:
        return None
    woke = [*keys, *([memory_key(memory)] if memory is not None else [])]
    if woke:
        coord_wake.mark_woke(agent_id, woke)
    return {"delivery": delivery, "widget": widget, "line": line}


def safe_wake(to: str, keys: list[str] | tuple[str, ...] = ()) -> dict[str, Any] | None:
    """wake() for a sender's command path: a failure here never fails the send or ack."""
    try:
        return wake(to, keys)
    except Exception:  # the ledger row is recorded; the recipient's hooks still see it
        return None


def nudge(kind: str, ref: str) -> None:
    """Best-effort ``POST /v1/waits/check {kind, ref}`` (Tether API 17): re-read now. Hint only."""
    from app.services import tether

    try:
        version = api_version()
        if version is None or version < NUDGE_API:
            return
        tether.request("POST", "/v1/waits/check", {"kind": kind, "ref": ref}, timeout=_NUDGE_TIMEOUT)
    except Exception:  # a lost nudge costs Tether's 60 s re-read
        return
