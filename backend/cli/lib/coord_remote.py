"""st sessions send between this computer and its agent hosts.

Each machine keeps its own coordination ledger (leases.LEASES_DIR). A request
between the workstation and an agent host lives in the workstation's ledger, so
its ack and confirm work as for a local one:

- To a window on an agent host (Tether lists it with ``host``), the request is
  recorded for ``<window>@<host>`` and the window gets a ``[Message]`` line on
  its gated delivery queue through the local Tether hub
  (``POST /v1/sessions/:id/deliveries``, Tether API 16; its ``st sessions inbox``
  reads the request from here). A host Tether without deliveries, or a shell,
  gets the request posted into the window (``/inject``) with how to ack, as before.
- On an agent host (``ST_AGENT_HOST``, set by the host's st guard), a target that
  is none of its own agents goes to the workstation's SummitFlow API
  (``POST /fleet/v1/coordination/requests``), which records it in the
  workstation ledger for the agent that id or window names, and wakes it the
  same way as a local send. Its ack reaches the sender's window the same way.
- On an agent host, ``st sessions ack``/``confirm`` for an id its own ledger
  lacks, and ``st sessions inbox``, go to the same API (the ``*_from_host``
  functions below answer them on the workstation).
"""

from __future__ import annotations

import os
import re
import socket
from http.client import HTTPException
from typing import Any
from urllib.parse import quote

from . import coord, coord_deliver, coord_route, coordinators, leases

# A host name in Tether's hosts.json (tether/src/hub/hosts.ts).
HOST = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
# A host request comes from an agent id, or the st:<session> id a shell in a Tether root resolves to.
SENDER = re.compile(r"(cc|codex|pi|agy|st|tmux):[\w-]+")
_NAMES = ("id", "ownershipId", "rootRequestId", "name", "label", "displayTitle")


def agent_host() -> str | None:
    """This machine's name when it is an agent host, else None (the workstation)."""
    value = os.environ.get("ST_AGENT_HOST", "").strip()
    return value if HOST.fullmatch(value) else None


def windows(target: str) -> list[dict[str, Any]]:
    """Aico/Tether windows named exactly by ``target`` (case-insensitive): widget
    id, st aico create request id, title or tmux name. Empty when Tether is absent."""
    from app.services import tether

    want = target.strip().casefold()
    out: list[dict[str, Any]] = []
    for status, body in tether.request_all("/v1/sessions"):
        items = body.get("items") if status == 200 and isinstance(body, dict) else None
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            names = {str(item.get(k) or "").casefold() for k in _NAMES}
            tmux = item.get("tmux")
            if isinstance(tmux, dict) and isinstance(tmux.get("sessionName"), str):
                names.add(tmux["sessionName"].casefold())
            if want and want in names:
                out.append(item)
    return out


def _sender() -> tuple[str, str]:
    """(who I am, what to reply to): my agent id, and my window when I have one."""
    agent_id = leases.identify_agent()[0]
    widget = os.environ.get("AICO_WIDGET_ID", "")
    return agent_id, widget if re.fullmatch(r"[0-9a-f]{8}", widget) else ""


def deliver(window: dict[str, Any], address: str) -> dict[str, Any] | None:
    """Queue the ``[Message]`` line for ``address`` on a host window's gated queue (through the hub).

    None when it was not taken: the hub or the host's Tether predates
    deliveries (API 16), or the window is a shell. The caller then injects.
    """
    if not coord_deliver.enabled():
        return None
    line = coord_deliver.summary(address)
    if line is None:
        return None
    return coord_deliver.post(str(window["id"]), coord_deliver.SOURCE_PREFIX + address, line)


def inject(window: dict[str, Any], framed: str) -> None:
    """Post text into a window on an agent host (Tether before deliveries); raises ValueError when it was not taken."""
    from app.services import tether

    try:
        status, data = tether.request("POST", f"/v1/sessions/{quote(str(window['id']), safe='')}/inject",
                                      {"generation": window.get("generation"), "text": framed,
                                       "mode": "paste", "submit": True}, timeout=10)
    except (OSError, HTTPException) as exc:
        raise ValueError(f"window {window['id']} on {window.get('host')} did not take it "
                         f"(Tether did not answer: {type(exc).__name__})") from exc
    if status != 200:
        error = data.get("error") if isinstance(data, dict) else None
        reason = data.get("reason") if isinstance(data, dict) else None
        raise ValueError(f"window {window['id']} on {window.get('host')} did not take it "
                         f"({error or status}{f': {reason}' if reason else ''})")


def to_host_window(target: str, text: str, *, project: str | None = None,
                   source_key: str | None = None) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Record a request for the one window on an agent host that ``target`` names
    and post it there: (window, ledger row). None when it names none (a local
    agent, or nothing). A duplicate of an open request is not posted again."""
    if coord_route.AGENT_ID.fullmatch(target):
        # An agent id names a ledger identity, never a window.
        return None
    found = [item for item in windows(target) if isinstance(item.get("host"), str)]
    if not found:
        return None
    if len(found) > 1:
        names = "; ".join(f"{item.get('id')} on {item.get('host')}" for item in found)
        raise ValueError(f"{target!r} names {len(found)} windows on agent hosts; send to one widget id: {names}")
    window = found[0]
    agent_id, widget = _sender()
    address = f"{window['id']}@{window['host']}"
    row = coord.send(address, text, project=project, source_key=source_key)
    if row.get("duplicate"):
        return window, row
    if delivery := deliver(window, address):
        return window, {**row, "delivery": delivery}
    sender = f"{agent_id}{f' (window {widget})' if widget else ''}"
    try:
        inject(window, f"[st sessions send {row['id']} from {sender} on {socket.gethostname()}] {row['text']} "
                       f"(Answer with: st sessions ack {row['id']} yes|no 'reason'|eta:MIN)")
    except ValueError:
        coord.drop(row["id"])  # never delivered, so a retry (same text or source key) sends it again
        raise
    return window, row


def names_local_agent(target: str) -> bool:
    """True when ``target`` names an agent of this machine's own ledger or windows."""
    return coord.known_target(target) or any(not item.get("host") for item in windows(target))


def resolve_workstation_target(target: str) -> str:
    """The workstation agent a host's request names: a registered id or a window here."""
    if coord.known_target(target):
        return target
    for alias in dict.fromkeys([target.strip().casefold(),
                                *(str(item.get("id")) for item in windows(target) if not item.get("host"))]):
        if agent := coordinators.agent_for_widget(alias):
            return agent
    raise LookupError(f"{target!r} names no agent on the workstation")


def record_from_host(target: str, text: str, *, sender: str, host: str,
                     reply_to: str | None = None) -> dict[str, Any]:
    """Record a host agent's request in this (the workstation's) ledger."""
    if not HOST.fullmatch(host):
        raise ValueError("invalid host name")
    if not SENDER.fullmatch(sender):
        raise ValueError("invalid sender id")
    if reply_to is not None and not re.fullmatch(r"[0-9a-f]{8}", reply_to):
        raise ValueError("invalid reply window")
    to = resolve_workstation_target(target)
    answer = reply_to or sender
    note = f" (from {sender} on {host}; longer answers: st sessions send {answer} '<answer>')"
    body = coord._clean_text(text)
    row = coord.send(to, body + note, limit=coord.MAX_TEXT + len(note), sender=f"{sender}@{host}",
                     remote={"host": host, "reply_window": reply_to} if reply_to else {"host": host})
    if not row.get("duplicate"):
        coord_deliver.safe_wake(to, [f"{row['id']}:req"])
    return row


def post_ack(row: dict[str, Any]) -> dict[str, Any] | None:
    """Post a workstation agent's ack into the host window that sent the request;
    the window it went to, or None when the request came from no host window.
    Raises ValueError when the window is gone or did not take it."""
    host, window_id = row.get("host"), row.get("reply_window")
    if not host or not window_id:
        return None
    found = [item for item in windows(str(window_id)) if item.get("host") == host and item.get("id") == window_id]
    if not found:
        raise ValueError(f"window {window_id} on {host} is not open")
    if deliver(found[0], str(row["from"])):
        return found[0]
    intent = row["intent"] + (f" {row['eta_min']}m" if row.get("eta_min") else "")
    note = f" ({row['note']})" if row.get("note") else ""
    inject(found[0], f"[st sessions ack from {row.get('acked_by')} on {socket.gethostname()}] "
                     f"ACK {row['id']} {intent}{note}; close: st sessions confirm {row['id']}")
    return found[0]


def _host_ids(host: str, senders: list[str], window: str | None) -> tuple[set[str], str | None]:
    """Validated (ledger sender ids, window address) of a host agent."""
    if not HOST.fullmatch(host):
        raise ValueError("invalid host name")
    if not senders or not all(SENDER.fullmatch(s) for s in senders):
        raise ValueError("invalid sender id")
    if window is not None and not re.fullmatch(r"[0-9a-f]{8}", window):
        raise ValueError("invalid window")
    return {f"{s}@{host}" for s in senders}, f"{window}@{host}" if window else None


def ack_from_host(message_id: str, intent: str, note: str | None, *, sender: str, host: str,
                  window: str) -> dict[str, Any]:
    """A host agent acks a request this ledger holds for its window."""
    ids, address = _host_ids(host, [sender], window)
    row = coord.ack(message_id, intent, note, remote=(next(iter(ids)), str(address)))
    coord_deliver.nudge("reply", row["id"])
    coord_deliver.safe_wake(str(row["from"]), [f"{row['id']}:ack:{row.get('acked_at')}"])
    return row


def confirm_from_host(message_id: str, *, senders: list[str], host: str, withdraw: bool = False) -> dict[str, Any]:
    """A host agent closes (or withdraws) a request it sent here."""
    return coord.confirm(message_id, withdraw=withdraw, senders=_host_ids(host, senders, None)[0])


def inbox_for_host(*, senders: list[str], host: str, window: str | None) -> list[dict[str, Any]]:
    """Requests in this ledger awaiting a host agent's ack, or sent by it and not yet closed."""
    ids, address = _host_ids(host, senders, window)
    with leases._lock("_coord"):
        rows = coord._load_ledger()
    return [row for row in rows if row["state"] != "closed"
            and ((row["state"] == "open" and address and row["to"] == address) or row["from"] in ids)]
