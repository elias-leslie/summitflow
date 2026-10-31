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
from typing import Any, NamedTuple
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
LINE_MAX = 500  # Tether noteMaxChars
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


class Target(NamedTuple):
    """Where a recipient's line goes: its window, the id it is posted and recorded under, and who it covers.

    ``family`` is every identity the recipient's own inbox answers for (its
    harness process's ids, as cli.lib.leases.self_ids sees them from inside), so
    the line counts what its turn hook will show.
    """

    widget: str
    agent_id: str
    family: frozenset[str]
    sessions: tuple[str, ...] = ()


def _nested(anchor: str) -> bool:
    """A harness started under another harness (a headless ``claude -p`` an agent runs) inherits its window."""
    info = coord_lineage._stat(int(anchor.partition(":")[0]))
    return info is not None and coord_lineage._proc_anchor(info[1]) is not None


def _window_anchors(widget: str) -> list[str]:
    coordinators._harness_widgets.cache_clear()  # long-lived callers (a 6 h watcher) look afresh
    return [a for a in coordinators._harness_widgets().get(widget) or () if not _nested(a)]


def target(to: str) -> Target | None:
    """The Aico window (Tether session) a local recipient is the live agent of, or None.

    Only the window's own agent is woken there: its newest main-thread identity
    or a main-thread predecessor on the same process (a context reset). A Codex
    child thread, a harness nested under another one, and an identity on a
    process that is no longer the window's newest keep today's path. agy has no
    delivery in Tether (409); ``<window>@<host>`` is coord_remote's.
    """
    if not to or "@" in to or to.startswith("agy:"):
        return None
    found = _identity(to)
    if found is None:
        return None
    agent_id, row = found
    anchor = row.get("anchor")
    if not isinstance(anchor, str) or not coord_lineage.anchor_alive(anchor) or _nested(anchor):
        return None
    widget = coordinators.widget_for_anchor(anchor)
    if not widget or not _WIDGET.fullmatch(widget):
        return None
    identities = coord_lineage.load_doc().get("identities") or {}
    rows = {aid: r for aid, r in identities.items() if isinstance(r, dict) and r.get("anchor") in _window_anchors(widget)}
    if not rows or max((str(r.get("last") or ""), str(r.get("anchor"))) for r in rows.values())[1] != anchor:
        return None  # the window's newest agent runs in another process
    family = {aid: r for aid, r in rows.items() if r.get("anchor") == anchor}
    mains = {aid for aid, r in family.items() if r.get("main")} or set(family)
    if agent_id not in mains:
        return None  # a child thread keeps its own inbox
    current = max(mains, key=lambda aid: str(family[aid].get("last") or ""))
    sessions = tuple(str(r.get("session")) for r in family.values() if r.get("session"))
    return Target(widget, current, frozenset(family), sessions)


def widget_for(to: str) -> str | None:
    found = target(to)
    return found.widget if found else None


# ---------------------------------------------------------------- the line

def _names(ids: list[str], named: int) -> str:
    shown = list(dict.fromkeys(i for i in ids if _ID.fullmatch(i)))
    if not shown or not named:
        return f"{len(shown)} agents" if len(shown) > 1 else "another agent"
    extra = len(shown) - named
    return ", ".join(shown[:named]) + (f" +{extra}" if extra > 0 else "")


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def waiting(who: Target) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(open requests to the recipient, acks of its requests it has not been shown) in the ledger.

    The same scope as its inbox (cli.lib.coord.inbox): any of its family's ids or a 13+ char prefix of
    their sessions.
    """
    seen = coord_wake.load_seen(who.agent_id)

    def addressed(row_to: str) -> bool:
        return row_to in who.family or (len(row_to) >= 13 and any(s.startswith(row_to) for s in who.sessions))

    with leases._lock("_coord"):
        rows = coord._load_ledger()
    requests = [r for r in rows if r["state"] == "open" and addressed(str(r["to"])) and r["from"] not in who.family]
    acks = [r for r in rows if r["state"] == "acked" and r["from"] in who.family
            and f"{r['id']}:ack:{r.get('acked_at')}" not in seen]
    return requests, acks


def summary(who: Target, *, memory: bool = False) -> str | None:
    """``[Message] 2 requests from cc:1c7a9f, codex:019a2b · 1 ack from cc:65b53f · st sessions inbox``.

    Fewer names when long ids would pass Tether's line limit.
    """
    requests, acks = waiting(who)
    for named in (_NAMED, 1, 0):
        parts = []
        if requests:
            parts.append(f"{_plural(len(requests), 'request')} from {_names([str(r['from']) for r in requests], named)}")
        if acks:
            parts.append(f"{_plural(len(acks), 'ack')} from {_names([str(r.get('acked_by') or '') for r in acks], named)}")
        if memory:
            parts.append("a memory notice for this pane")
        if not parts:
            return None
        line = "[Message] " + " · ".join(parts) + f" · {LOOK}"
        if len(line) <= LINE_MAX:
            return line
    return line


# ---------------------------------------------------------------- queueing

class Unsettled(Exception):
    """Tether did not answer, or failed: the line may or may not be queued, so nothing else may type it."""


def post(widget: str, source: str, line: str, *, timeout: float = _TIMEOUT) -> dict[str, Any] | None:
    """Queue ``line`` on ``widget``'s delivery queue: Tether's record, or None when it refused it.

    Refused means a definite answer (404 unknown session, or a hub peer
    predating deliveries; 409 delivery_unsupported for shells and agy; 400), so
    the caller keeps its own path. No answer or a server error raises
    Unsettled. The hub forwards a session on another host to that host's Tether.
    """
    from app.services import tether

    try:
        status, body = tether.request("POST", f"/v1/sessions/{quote(widget, safe='')}/deliveries",
                                      {"source": source, "line": line}, timeout=timeout)
    except (OSError, ValueError, HTTPException) as exc:
        raise Unsettled(type(exc).__name__) from exc
    if status in (200, 201) and isinstance(body, dict) and body.get("id"):
        return body
    if status in (400, 404, 409):
        return None
    raise Unsettled(f"status {status}")


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
    kept). Returns ``{delivery, widget, line, agent_id}``, or None when the
    recipient keeps today's path (older Tether, no window it is the agent of,
    shell or agy, refused). Raises Unsettled when Tether did not answer: the
    caller then tries again later and never types the line itself.
    """
    if not enabled():
        return None
    who = target(to)
    if who is None:
        return None
    line = summary(who, memory=memory is not None)
    if line is None:
        return None
    woke = [*keys, *([memory_key(memory)] if memory is not None else [])]
    # Recorded before the POST, so the recipient's own watcher does not queue a second line meanwhile.
    stamp = coord_wake.mark_woke(who.agent_id, woke) if woke else None
    try:
        delivery = post(who.widget, SOURCE_PREFIX + who.agent_id, line)
    except Unsettled:
        if stamp is not None:
            coord_wake.unmark_woke(who.agent_id, woke, stamp)
        raise
    if delivery is None:
        if stamp is not None:
            coord_wake.unmark_woke(who.agent_id, woke, stamp)
        return None
    return {"delivery": delivery, "widget": who.widget, "line": line, "agent_id": who.agent_id}


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
