"""st sessions send between this computer and its agent hosts.

Each machine keeps its own coordination ledger (leases.LEASES_DIR), so a request
cannot be recorded for an agent on another machine. Instead:

- To a window on an agent host (Tether lists it with ``host``), the text is
  posted into it through the local Tether hub (``POST /v1/sessions/:id/inject``),
  with the sender and how to reply.
- On an agent host (``ST_AGENT_HOST``, set by the host's st guard), a target that
  is none of its own agents goes to the workstation's SummitFlow API
  (``POST /fleet/v1/coordination/requests``), which records it in the
  workstation ledger for the agent that id or window names.
"""

from __future__ import annotations

import os
import re
import socket
from typing import Any
from urllib.parse import quote

from . import coord, coord_route, coordinators, leases

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


def inject(window: dict[str, Any], text: str, *, sender: str, reply_to: str, origin: str) -> None:
    """Post a request into a window on an agent host; raises ValueError when it was not taken."""
    from app.services import tether

    body = coord._clean_text(text)
    framed = (f"[st sessions send from {sender} on {origin}] {body} "
              f"(Reply with: st sessions send {reply_to} '<answer>')")
    status, data = tether.request("POST", f"/v1/sessions/{quote(str(window['id']), safe='')}/inject",
                                  {"generation": window.get("generation"), "text": framed,
                                   "mode": "paste", "submit": True}, timeout=10)
    if status != 200:
        error = data.get("error") if isinstance(data, dict) else None
        reason = data.get("reason") if isinstance(data, dict) else None
        raise ValueError(f"window {window['id']} on {window.get('host')} did not take it "
                         f"({error or status}{f': {reason}' if reason else ''})")


def to_host_window(target: str, text: str) -> dict[str, Any] | None:
    """Deliver to the one window on an agent host that ``target`` names; None when
    it names none (a local agent, or nothing)."""
    if coord_route.AGENT_ID.fullmatch(target):
        # An agent id names a ledger identity, never a window.
        return None
    found = [item for item in windows(target) if isinstance(item.get("host"), str)]
    if not found:
        return None
    if len(found) > 1:
        names = "; ".join(f"{item.get('id')} on {item.get('host')}" for item in found)
        raise ValueError(f"{target!r} names {len(found)} windows on agent hosts; send to one widget id: {names}")
    agent_id, widget = _sender()
    inject(found[0], text, sender=f"{agent_id}{f' (window {widget})' if widget else ''}",
           reply_to=agent_id, origin=socket.gethostname())
    return found[0]


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
    note = f" (from {sender} on {host}; reply with: st sessions send {answer} '<answer>')"
    body = coord._clean_text(text)
    return coord.send(to, body + note, limit=coord.MAX_TEXT + len(note), sender=f"{sender}@{host}")
