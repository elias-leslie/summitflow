"""Which coordinator a session belongs to, read from Tether's session catalog.

Tether is the one record of names and coordinator lineage, and words the
title once (descriptor fields ``displayTitle``, ``coordinator``,
``coordinatorId``; docs/api-v1.md "Coordinators" and "Display title and
badge" in the tether repo). A Tether session id is the Aico widget id its harness sees as
``AICO_WIDGET_ID``; agent ids come from the coordination identity registry.
Every lookup is best effort: without Tether, lines stay as they were.
"""

from __future__ import annotations

import http.client
import os
from functools import cache
from pathlib import Path
from typing import Any

from . import coord_lineage, leases

_TIMEOUT = 0.5


def _get(path: str) -> Any:
    from app.services import tether

    if not tether.socket_present():
        return None
    try:
        status, data = tether.request("GET", path, timeout=_TIMEOUT)
    except (OSError, ValueError, http.client.HTTPException):
        return None
    return data if status == 200 else None


@cache
def sessions() -> dict[str, dict[str, Any]]:
    """Running Tether session descriptors by id (= Aico widget id)."""
    data = _get("/v1/sessions")
    items = data.get("items") if isinstance(data, dict) else None
    return {str(d["id"]): d for d in items or [] if isinstance(d, dict) and d.get("id")}


def title(desc: dict[str, Any]) -> str:
    """Tether's ``displayTitle`` (`Project — Task`), as Aico and A-Term show it."""
    shown = str(desc.get("displayTitle") or "").strip()
    return shown or str(desc.get("label") or desc.get("id") or "?")


# ---------------------------------------------------------------- agents <-> widgets

def _environ(pid: int) -> dict[str, str]:
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return {}
    pairs = (item.partition(b"=") for item in raw.split(b"\0") if item)
    return {k.decode(errors="replace"): v.decode(errors="replace") for k, _, v in pairs}


def widget_for_anchor(anchor: str | None) -> str | None:
    """The Aico widget (Tether session) a live harness process runs in."""
    if not anchor or not coord_lineage.anchor_alive(anchor):
        return None
    return _environ(int(anchor.partition(":")[0])).get("AICO_WIDGET_ID") or None


@cache
def _harness_widgets() -> dict[str, str]:
    """Live harness anchors by the widget they run in (the oldest process wins a widget)."""
    found: dict[str, tuple[int, str]] = {}
    uid = os.getuid()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
        except OSError:
            continue
        pid = int(entry.name)
        info = coord_lineage._stat(pid)
        if info is None or info[0] not in coord_lineage.HARNESS_COMMS:
            continue
        widget = _environ(pid).get("AICO_WIDGET_ID")
        if not widget:
            continue
        start = int(info[2])
        if widget not in found or start < found[widget][0]:
            found[widget] = (start, f"{pid}:{info[2]}")
    return {widget: anchor for widget, (_, anchor) in found.items()}


def agent_for_widget(widget: str) -> str | None:
    """Coordination id of the agent in ``widget``: the latest identity on its harness process."""
    anchor = _harness_widgets().get(widget)
    if anchor is None:
        return None
    identities = coord_lineage.load_doc().get("identities") or {}
    mine = [(str(row.get("last") or ""), aid) for aid, row in identities.items()
            if isinstance(row, dict) and row.get("anchor") == anchor]
    return max(mine)[1] if mine else None


def lease_widget(lease: leases.Lease) -> str | None:
    identities = coord_lineage.load_doc().get("identities") or {}
    return widget_for_anchor(lease.anchor or (identities.get(lease.agent_id) or {}).get("anchor"))


def widget_for_session(session: dict[str, Any]) -> str | None:
    """Tether session of a SummitFlow agent session record (Tether names tmux sessions ``aico-<id>``)."""
    identity = session.get("external_identity")
    widget = identity.get("aico_widget_id") if isinstance(identity, dict) else None
    name = str(session.get("tmux_session_name") or "")
    return str(widget) if widget else (name.removeprefix("aico-") if name.startswith("aico-") else None)


# ---------------------------------------------------------------- lines

def coordinator_of(widget: str | None) -> dict[str, Any] | None:
    """``{id, title, agent_id}`` of the root coordinator ``widget`` belongs to; None for coordinators and loose sessions."""
    desc = sessions().get(widget or "")
    coordinator_id = desc.get("coordinatorId") if desc else None
    if not desc or not coordinator_id or desc.get("coordinator"):
        return None
    coordinator = sessions().get(str(coordinator_id))
    return {
        "id": str(coordinator_id),
        # An ended coordinator keeps its lanes' lineage but has no descriptor left.
        "title": title(coordinator) if coordinator else "Coordinator",
        "agent_id": agent_for_widget(str(coordinator_id)) if coordinator else None,
    }


def belongs_to(widget: str | None) -> str | None:
    """`belongs to <title> (<agent id>)`, or None."""
    owner = coordinator_of(widget)
    if owner is None:
        return None
    agent = f" ({owner['agent_id']})" if owner["agent_id"] else ""
    return f"belongs to {owner['title']}{agent}"


def session_summary(widget: str | None) -> dict[str, Any] | None:
    """Title and coordinator lineage of one Tether session, for listings."""
    desc = sessions().get(widget or "")
    if desc is None:
        return None
    return {
        "widget_id": widget,
        "title": title(desc),
        "coordinator": bool(desc.get("coordinator")),
        "belongs_to": coordinator_of(widget),
    }


def unrecorded_coordinators(listed: set[str | None]) -> list[dict[str, Any]]:
    """Live coordinators with no agent session record (Personal Workspace sessions are never ingested)."""
    try:
        return [
            {"widget_id": wid, "agent_id": agent_for_widget(wid), "project_id": desc.get("projectId"),
             "title": title(desc), "coordinator": True, "belongs_to": None}
            for wid, desc in sessions().items()
            if desc.get("coordinator") and wid not in listed
        ]
    except Exception:  # listing stays best effort without Tether
        return []


def unrecorded_line(entry: dict[str, Any]) -> str:
    """Compact line for an ``unrecorded_coordinators`` entry, shaped like a session line."""
    return (f"SES {entry['project_id'] or '-'} | active | - | {entry['agent_id'] or entry['widget_id']} | "
            f"task=- state=no-session-record | {entry['title']} | coordinator")


def session_suffix(widget: str | None) -> str:
    """` | <title> | coordinator` or ` | <title> | belongs to ...` for one compact session line."""
    try:
        summary = session_summary(widget)
        if summary is None:
            return ""
        role = "coordinator" if summary["coordinator"] else belongs_to(widget)
    except Exception:  # listing stays best effort without Tether
        return ""
    return f" | {summary['title']}" + (f" | {role}" if role else "")


def conflict_suffix(lease: leases.Lease) -> str:
    """`; belongs to <title> (<agent id>); raise conflicts there` for a lease held by a coordinated lane."""
    try:
        line = belongs_to(lease_widget(lease))
    except Exception:  # hints stay best effort; the conflict line must still print
        return ""
    return f"; {line}; raise conflicts there" if line else ""
