"""Send-time addressing for the handshake ledger.

The ledger matches recipients only by agent id (or a 13+ char session prefix),
so a label such as an Agent Hub session name or a tmux session name is resolved
to exactly one live agent id before it is recorded, never stored verbatim.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from . import coord_lineage, leases

AGENT_ID = re.compile(r"(cc|codex|pi|agy|tmux):[\w-]+")
# Agent Hub session fields that name a session for a human (title/name when the
# owner exposes them; otherwise its persona, tmux session and Aico widget).
_SESSION_NAME_FIELDS = ("title", "name", "display_title", "agent_slug", "tmux_session_name")
_IDENTITY_NAME_FIELDS = ("display_identity", "aico_widget_id", "aico_session_id")


def _live_identities() -> dict[str, dict[str, Any]]:
    identities = coord_lineage.load_doc().get("identities") or {}
    return {aid: row for aid, row in identities.items()
            if isinstance(row, dict) and coord_lineage.anchor_alive(row.get("anchor"))}


def live_agent_for_session(session_id: str) -> str | None:
    """The live agent id registered for an exact native session id, if any."""
    return next((aid for aid, row in _live_identities().items() if row.get("session") == session_id), None)


def _session_names(session: dict[str, Any]) -> set[str]:
    external = session.get("external_identity")
    external = external if isinstance(external, dict) else {}
    values = [session.get(f) for f in _SESSION_NAME_FIELDS] + [external.get(f) for f in _IDENTITY_NAME_FIELDS]
    return {v.casefold() for v in values if isinstance(v, str) and v.strip()}


def _live_leases() -> list[leases.Lease]:
    out: list[leases.Lease] = []
    for project in leases.all_projects():
        try:
            out.extend(leases.list_active(project, kinds=("file", "hold", "op")))
        except (OSError, ValueError):
            continue
    return out


def resolve_label(label: str, sessions: Iterable[dict[str, Any]] = ()) -> tuple[dict[str, str], list[str]]:
    """Live agent ids a label names ({agent_id: how}), plus named sessions that have no live identity.

    Matches are exact and case-insensitive: an active Agent Hub session's
    title/name/persona/tmux session/Aico widget, a live identity's short id or
    session prefix (6+ chars), or a live lease holder's slug.
    """
    want = label.strip().casefold()
    if not want:
        return {}, []
    live = _live_identities()
    by_session = {str(row["session"]): aid for aid, row in live.items() if row.get("session")}
    found: dict[str, str] = {}
    unreachable: list[str] = []
    for session in sessions:
        if not isinstance(session, dict) or want not in _session_names(session):
            continue
        sid = str(session.get("id") or "")
        aid = by_session.get(sid) or by_session.get(str(session.get("parent_session_id") or ""))
        if aid:
            found.setdefault(aid, f"agent-hub session {sid[:8]}")
        else:
            unreachable.append(f"agent-hub session {sid[:8]} (no live coordination identity)")
    for aid, row in live.items():
        session = str(row.get("session") or "").casefold()
        if want == aid.partition(":")[2].casefold() or (len(want) >= 6 and session.startswith(want)):
            found.setdefault(aid, "coordination identity")
    for lease in _live_leases():
        if want in {lease.agent_slug.casefold(), lease.agent_id.partition(":")[2].casefold()}:
            found.setdefault(lease.agent_id, f"lease holder ({lease.agent_slug})")
    return found, unreachable
