"""Coordination inbox wakes through Tether's gated delivery queue.

Since Tether API 16 (tether docs/api-v1.md "Deliveries") the inbox no longer
types into panes or wakes harnesses on its own when it can name the
recipient's Aico window: it queues one content-free line on that window's
delivery queue (``POST /v1/sessions/<widget>/deliveries``), and Tether pastes
it once the agent is idle, nobody is typing and the input is empty, hands it to
a native puller, or gives an Agent Hub chat a turn. The agent's own turn hook
(scripts/lib/coord_inbox.py) still shows the content. The line comes from
typed values only (counts, agent ids and the senders' Aico window titles),
never request or reply text, so case details stay out of notices.

One source per recipient (``coord:<agent id>``) coalesces: a newer line
replaces an undelivered one, so the line always summarises everything the
recipient has waiting. What was queued for which inbox item is kept in the
recipient's content-free woke state (cli.lib.coord_wake), so the recipient's
own watcher does not wake it a second time for the same item.

Unresolved recipients, shells and an older Tether keep today's path (an agy
window takes lines from Tether API 18; an older one refuses with 409):
every function here answers None and the caller carries on as before.

An ack the recipient armed a reply wait for (``st aico wait reply REQ``) is left out of
the line: Tether's ``[Ready] request ... answered`` line for that wait is its one wake.

Two delivery classes (Tether API 24, "Deliveries"). A line that names a request, an ack with a note or an
eta, or a memory notice is a wake, as before. A line that names only ride-along items (an FYI note from
``st sessions send --fyi``, a bare ``ack yes`` that closed the request for its sender: coord.close_bare_ack) is
queued with ``ride: true``: Tether never pastes it or wakes a puller for it, and it joins the next wake or the
window's next turn. Against a Tether older than 24 the line is posted plain, as before.

``from`` names only the Aico window of the agent whose command queued the line (``sender``), never every agent
the line counts: a recipient's own watcher and ``withdraw_stale`` pass none. A request (``st sessions send``) tells
the recipient something, so a lane that sent its launcher one in a turn gets no went-idle line for it. An ack is a
``reply`` (Tether API 25): it counts as its sender acting on the recipient (a lane's repeat went-idle backoff starts
over) but never as telling it, since an ack (an eta, "yes, starting") may open a turn of work whose end the
requester still needs to hear. Before API 25 an ack carries no ``from``.

A line that goes stale before it is pasted (the request was answered, the ack
shown by the turn hook) is taken back: the turn hook calls ``withdraw_stale``
once the recipient's inbox has nothing waiting (Tether API 18).
"""

from __future__ import annotations

import contextlib
import hashlib
import re
import time
from http.client import HTTPException
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import quote

from . import coord, coord_lineage, coord_wake, coordinators, leases

DELIVERY_API = 16  # POST /v1/sessions/:id/deliveries, GET /v1/deliveries/:id
NUDGE_API = 17  # POST /v1/waits/check
WITHDRAW_API = 18  # DELETE /v1/sessions/:id/deliveries?source=
RIDE_API = 24  # `ride` and `from` on a delivery; GET /v1/sessions/:id/due?ride=1
REPLY_API = 25  # `reply` on a delivery; GET /v1/sessions/:id/due?ride=peek, DELETE .../due?token=
SOURCE_PREFIX = "coord:"
_TIMEOUT = 2.0
_NUDGE_TIMEOUT = 0.5
# What a line may name: agent ids (cc:1c7a9f, codex:019a…, pi:…, st:…, with @host for a host agent).
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,15}:[A-Za-z0-9_.-]{1,64}(@[a-z0-9][a-z0-9-]{0,31})?")
_WIDGET = re.compile(r"[0-9a-f]{8}")
_NAMED = 3  # senders named on one line before "+N"
TITLE_MAX = 40  # a sender's window title on the line, in characters
_DASH = " \u2014 "  # Tether's displayTitle is "Project — Task"
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
    process that is no longer the window's newest keep today's path. An agy
    window takes lines from Tether API 18 (older: 409); ``<window>@<host>`` is coord_remote's.
    """
    if not to or "@" in to:
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

def _clean_title(shown: str) -> str | None:
    """The task part of a window title, one line, no double quotes, at most TITLE_MAX characters."""
    task = shown.rsplit(_DASH, 1)[-1]
    task = " ".join("".join(c if c.isprintable() else " " for c in task).replace('"', "'").split())
    if not task:
        return None
    return task if len(task) <= TITLE_MAX else task[:TITLE_MAX - 1].rstrip() + "\u2026"


def window_title(agent_id: str) -> str | None:
    """The Aico window title (Tether ``displayTitle``) of the window a local agent runs in, or None."""
    found = _identity(agent_id)
    anchor = found[1].get("anchor") if found else None
    if not isinstance(anchor, str):
        return None
    try:
        widget = coordinators.widget_for_anchor(anchor)
        desc = coordinators.sessions().get(widget or "") if widget else None
    except Exception:  # best effort: the id alone names the sender
        return None
    shown = str((desc or {}).get("displayTitle") or "").strip()
    return _clean_title(shown) if shown else None


def _names(ids: list[str], named: int, titles: dict[str, str]) -> str:
    shown = list(dict.fromkeys(i for i in ids if _ID.fullmatch(i)))
    if not shown or not named:
        return f"{len(shown)} agents" if len(shown) > 1 else "another agent"
    extra = len(shown) - named
    return ", ".join(f'"{titles[i]}" ({i})' if i in titles else i for i in shown[:named]) + (
        f" +{extra}" if extra > 0 else "")


def _counted(count: int, word: str) -> str:
    """``Request`` for one, ``2 requests`` for more."""
    return word.capitalize() if count == 1 else f"{count} {word}s"


def reply_waited(widget: str) -> set[str]:
    """Requests whose ack this window's own reply wait reports: ``st aico wait reply REQ`` (until acked).

    Armed, or already fired by the answer. A wait until closed does not fire on the ack, so it does not
    count, nor does one on another host's ledger. Empty when Tether does not answer: the ack then gets
    its line.
    """
    from app.services import tether

    try:
        status, body = tether.request("GET", f"/v1/sessions/{quote(widget, safe='')}/waits?recent=1",
                                      timeout=_NUDGE_TIMEOUT)
    except Exception:  # an ack with no line is worse than one line too many
        return set()
    items = body.get("items") if status == 200 and isinstance(body, dict) else None
    return {str(w["ref"]) for w in items or () if isinstance(w, dict) and w.get("kind") == "reply"
            and w.get("until") == "acked" and not w.get("host") and isinstance(w.get("ref"), str)
            and (w.get("state") == "armed" or (w.get("state") == "fired" and w.get("outcome") == "until"))}


def waiting(who: Target) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(open requests to the recipient, acks of its requests it has not been shown) in the ledger.

    The same scope as its inbox (cli.lib.coord.inbox): any of its family's ids or a 13+ char prefix of
    their sessions. Acks its own reply wait reports (``reply_waited``) are left out.
    """
    seen = coord_wake.load_seen(who.agent_id)

    def addressed(row_to: str) -> bool:
        return row_to in who.family or (len(row_to) >= 13 and any(s.startswith(row_to) for s in who.sessions))

    with leases._lock("_coord"):
        rows = coord._load_ledger()
    requests = [r for r in rows if r["state"] == "open" and addressed(str(r["to"])) and r["from"] not in who.family]
    acks = [r for r in rows if r["state"] == "acked" and r["from"] in who.family
            and f"{r['id']}:ack:{r.get('acked_at')}" not in seen]
    if acks and (waited := reply_waited(who.widget)):
        acks = [r for r in acks if not any(str(r["id"]).startswith(ref) for ref in waited)]
    return requests, acks


def rides(who: Target) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(FYI notes to the recipient, bare acks that closed its requests) it has not been shown: ride-along only."""
    seen = coord_wake.load_seen(who.agent_id)

    def addressed(row_to: str) -> bool:
        return row_to in who.family or (len(row_to) >= 13 and any(s.startswith(row_to) for s in who.sessions))

    with leases._lock("_coord"):
        rows = coord._load_ledger()
    fyis = [r for r in rows if r["state"] == "fyi" and addressed(str(r["to"])) and r["from"] not in who.family
            and f"{r['id']}:fyi" not in seen]
    closed = [r for r in rows if r["state"] == "closed" and r.get("auto_closed") and r["from"] in who.family
              and f"{r['id']}:ack:{r.get('acked_at')}" not in seen]
    return fyis, closed


class Line(NamedTuple):
    """A recipient's line: its text, and whether it is ride-along only."""

    text: str
    ride: bool


def _plural(count: int, one: str, many: str) -> str:
    return one if count == 1 else f"{count} {many}"


def compose(who: Target, *, memory: bool = False, ride_items: bool = True) -> Line | None:
    """``[Message] Request from "Neri P2a acceptance" (codex:619a52) · Ack from cc:65b53f · st sessions inbox``.

    Each sender is named by its Aico window title when it has one. Fewer names, then no titles, when
    the line would pass Tether's line limit. ``ride_items`` false leaves FYI notes and closed acks out
    (a line for a window on another host: coord_remote).
    """
    requests, acks = waiting(who)
    fyis, closed = rides(who) if ride_items else ([], [])
    if not (requests or acks or memory or fyis or closed):
        return None
    senders = [str(r["from"]) for r in requests]
    ackers = [str(r.get("acked_by") or "") for r in acks]
    notes = [str(r["from"]) for r in fyis]
    closers = [str(r.get("acked_by") or "") for r in closed]
    if requests or acks or fyis or closed:
        coordinators.sessions.cache_clear()  # long-lived callers (a 6 h watcher) see renamed windows
    titles = {i: t for i in dict.fromkeys(senders[:_NAMED] + ackers[:_NAMED] + notes[:_NAMED] + closers[:_NAMED])
              if _ID.fullmatch(i) and (t := window_title(i))}
    line = ""
    for named, shown in ((_NAMED, titles), (1, titles), (_NAMED, {}), (1, {}), (0, {})):
        parts = []
        if requests:
            parts.append(f"{_counted(len(requests), 'request')} from {_names(senders, named, shown)}")
        if acks:
            parts.append(f"{_counted(len(acks), 'ack')} from {_names(ackers, named, shown)}")
        if memory:
            parts.append("a memory notice for this pane")
        if fyis:
            parts.append(f"{_plural(len(fyis), 'FYI', 'FYIs')} from {_names(notes, named, shown)}")
        if closed:
            parts.append(f"{_counted(len(closed), 'ack')} from {_names(closers, named, shown)} (closed)")
        line = "[Message] " + " · ".join(parts) + f" · {LOOK}"
        if len(line) <= LINE_MAX:
            break
    return Line(line, not (requests or acks or memory))


def summary(who: Target, *, memory: bool = False, ride_items: bool = True) -> str | None:
    """The text of ``compose``, or None when nothing is waiting."""
    line = compose(who, memory=memory, ride_items=ride_items)
    return line.text if line else None


def window_of(agent_id: str) -> str | None:
    """The Aico window an agent of this computer runs in (its newest anchor's), or None; ``@host`` ids have none here."""
    if not agent_id or "@" in agent_id:
        return None
    found = _identity(agent_id)
    anchor = found[1].get("anchor") if found else None
    if not isinstance(anchor, str):
        return None
    try:
        widget = coordinators.widget_for_anchor(anchor)
    except Exception:  # best effort: no window, no "told" record
        return None
    return widget if widget and _WIDGET.fullmatch(widget) else None


def settle_bare_ack(row: dict[str, Any]) -> dict[str, Any]:
    """Close an acked request for its sender when the ack is a bare ``yes`` it waits on nothing for.

    A ``yes`` with no note, a sender on this computer, and no ``st aico wait reply`` armed (or fired) for
    the request: the ack is ride-along and needs no confirm. Notes, ``no``, eta acks, a request that came from
    an agent host, and a sender whose reply wait covers it are left exactly as they were. The row returned is
    the ledger's, closed or not.
    """
    if row.get("intent") != "yes" or row.get("note") or row.get("host") or row.get("state") != "acked":
        return row
    if enabled() and (widget := window_of(str(row["from"]))) and any(
            str(row["id"]).startswith(ref) for ref in reply_waited(widget)):
        return row
    try:
        return coord.close_bare_ack(str(row["id"]))
    except ValueError:
        return row


class Ride(NamedTuple):
    """Tether's ride-along lines for a window: the text, and the token that takes them once shown (None: taken)."""

    text: str
    token: str | None = None


def take_ride(widget: str) -> Ride | None:
    """The ride-along lines Tether queued for this window, or None.

    From Tether API 25 they are only peeked (``GET .../due?ride=peek``): the caller shows the text, then
    ``confirm_ride`` takes them, so a hook that times out or is killed first loses none. API 24 takes them
    at once (``?ride=1``).
    """
    from app.services import tether

    if not _WIDGET.fullmatch(widget or ""):
        return None
    version = api_version()
    if version is None or version < RIDE_API:
        return None
    peek = version >= REPLY_API
    try:
        status, body = tether.request("GET", f"/v1/sessions/{quote(widget, safe='')}/due?ride={'peek' if peek else '1'}",
                                      timeout=_NUDGE_TIMEOUT)
    except Exception:  # best effort: they stay queued (peek) or join the next wake
        return None
    if status != 200 or not isinstance(body, dict):
        return None
    text, token = body.get("text"), body.get("token")
    if not isinstance(text, str) or not text:
        return None
    if peek and not isinstance(token, str):
        return None  # nothing to confirm with: leave them for the next turn
    return Ride(text, token if peek else None)


def confirm_ride(widget: str, ride: Ride) -> None:
    """Take the ride-along lines ``take_ride`` peeked, now that they were shown (``DELETE .../due?token=``)."""
    from app.services import tether

    if ride.token is None or not _WIDGET.fullmatch(widget or ""):
        return
    with contextlib.suppress(Exception):  # unconfirmed: shown again at the next turn, never lost
        tether.request("DELETE", f"/v1/sessions/{quote(widget, safe='')}/due?token={quote(ride.token, safe='')}",
                       timeout=_NUDGE_TIMEOUT)


# ---------------------------------------------------------------- queueing

class Unsettled(Exception):
    """Tether did not answer, or failed: the line may or may not be queued, so nothing else may type it."""


def post(widget: str, source: str, line: str, *, timeout: float = _TIMEOUT, ride: bool = False,
         senders: tuple[str, ...] = (), reply: bool = False) -> dict[str, Any] | None:
    """Queue ``line`` on ``widget``'s delivery queue: Tether's record, or None when it refused it.

    Refused means a definite answer (404 unknown session, or a hub peer
    predating deliveries; 409 delivery_unsupported for shells and agy; 400), so
    the caller keeps its own path. No answer or a server error raises
    Unsettled. The hub forwards a session on another host to that host's Tether.

    ``ride`` queues a ride-along line and ``senders`` (Aico windows) record who sent what it carries (both
    API 24); a Tether that does not answer with that version gets a plain line. ``reply`` marks the senders'
    line as an ack (API 25): they acted on this window but did not tell it anything; before 25 an ack names
    no senders.
    """
    from app.services import tether

    body_in: dict[str, Any] = {"source": source, "line": line}
    if ride or senders:
        version = api_version()
        if version is not None and version >= RIDE_API:
            if ride:
                body_in["ride"] = True
            if senders and (not reply or version >= REPLY_API):
                body_in["from"] = list(senders[:8])
                if reply:
                    body_in["reply"] = True
    try:
        status, body = tether.request("POST", f"/v1/sessions/{quote(widget, safe='')}/deliveries",
                                      body_in, timeout=timeout)
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


def wake(to: str, keys: list[str] | tuple[str, ...] = (), *, memory: str | None = None, sender: str | None = None,
         reply: bool = False) -> dict[str, Any] | None:
    """Queue the recipient's ``[Message]`` line through Tether and record ``keys`` as woken.

    ``memory`` is a memory notice's text for that recipient (only its key is
    kept). ``sender`` is the agent whose own command queues the line (a request, an FYI, with ``reply`` an
    ack): its window is the line's ``from``. Returns ``{delivery, widget, line, agent_id}``, or None when the
    recipient keeps today's path (older Tether, no window it is the agent of,
    a shell, refused). Raises Unsettled when Tether did not answer: the
    caller then tries again later and never types the line itself.
    """
    if not enabled():
        return None
    who = target(to)
    if who is None:
        return None
    line = compose(who, memory=memory is not None)
    if line is None:
        if keys:  # covered by the recipient's own reply wait (or gone): its watcher must not line it either
            coord_wake.mark_woke(who.agent_id, list(keys))
        return None
    woke = [*keys, *([memory_key(memory)] if memory is not None else [])]
    # Recorded before the POST, so the recipient's own watcher does not queue a second line meanwhile.
    stamp = coord_wake.mark_woke(who.agent_id, woke) if woke else None
    try:
        own = window_of(sender) if sender else None
        delivery = post(who.widget, SOURCE_PREFIX + who.agent_id, line.text, ride=line.ride,
                        senders=(own,) if own and own != who.widget else (), reply=reply)
    except Unsettled:
        if stamp is not None:
            coord_wake.unmark_woke(who.agent_id, woke, stamp)
        raise
    if delivery is None:
        if stamp is not None:
            coord_wake.unmark_woke(who.agent_id, woke, stamp)
        return None
    return {"delivery": delivery, "widget": who.widget, "line": line.text, "agent_id": who.agent_id,
            "ride": line.ride}


def safe_wake(to: str, keys: list[str] | tuple[str, ...] = (), *, sender: str | None = None,
              reply: bool = False) -> dict[str, Any] | None:
    """wake() for a sender's command path: a failure here never fails the send or ack."""
    try:
        return wake(to, keys, sender=sender, reply=reply)
    except Exception:  # the ledger row is recorded; the recipient's hooks still see it
        return None


def _withdrawn_path(agent_id: str) -> Path:
    return coord_wake.STATE / f"{coord_wake.state_key(agent_id)}.withdrawn"


def withdraw_stale(agent_id: str) -> bool | None:
    """Take back the agent's undelivered ``[Message]`` line once its inbox has nothing waiting (Tether API 18).

    The turn hook calls it after showing the inbox: a request answered or withdrawn, or an ack just shown,
    leaves the queued line stale, and Tether drops it before it is pasted (one already going out is not
    stopped). Only after a line was queued since the last withdraw, so most turns make no request. True
    when a line went, False when none was queued, None when not asked (nothing queued lately, something
    still waiting, no window, an older Tether, no answer).
    """
    woke = [v for v in coord_wake.load_woke(agent_id).values() if isinstance(v, (int, float))]
    path = _withdrawn_path(agent_id)
    try:
        last = float(path.read_text())
    except (OSError, ValueError):
        last = 0.0
    if not woke or max(woke) <= last:
        return None
    # Taken before the inbox read: a line a sender queues meanwhile is newer and gets its own look.
    began = time.time()
    who = target(agent_id)
    if who is None:
        return None
    left = compose(who)
    if left is not None and not left.ride:
        return None  # a request, an ack to answer or a memory notice still waits: the queued wake line stands
    version = api_version()
    if version is None or version < WITHDRAW_API:
        return None
    from app.services import tether

    source = quote(SOURCE_PREFIX + who.agent_id, safe="")
    try:
        status, body = tether.request("DELETE", f"/v1/sessions/{quote(who.widget, safe='')}/deliveries?source={source}",
                                      timeout=_NUDGE_TIMEOUT)
    except (OSError, ValueError, HTTPException):
        return None
    if status != 200 or not isinstance(body, dict):
        return None
    coord_wake.STATE.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{began:.3f}")
    withdrawn = bool(body.get("withdrawn"))
    # A sender's line merged into the queued one between the read and the DELETE went with it, and a ride-along
    # item still unseen keeps its own line: queue it again.
    if withdrawn and summary(who) is not None:
        with contextlib.suppress(Unsettled):
            wake(agent_id)
    return withdrawn


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
