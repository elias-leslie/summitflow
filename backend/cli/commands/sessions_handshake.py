"""Agent-to-agent request -> ack -> confirm on the shared coordination ledger."""

from __future__ import annotations

from typing import Annotated

import typer
from st_sdk.usage import USAGE_SPECS_ATTR, UsageSpec, usage

from ..config import get_config_optional
from ..lib import coord, leases


def _fail(exc: ValueError) -> None:
    typer.echo(f"ERROR {exc}", err=True)
    raise typer.Exit(2)


def send_request(to: str, text: str, source_key: str | None = None) -> None:
    cfg = get_config_optional()
    try:
        row = coord.send(to, text, project=getattr(cfg, "project_id", None) or None, source_key=source_key)
    except ValueError as exc:
        _fail(exc)
        return
    if row.get("duplicate"):
        why = "same source key" if source_key and row.get("source_key") == source_key else "same open text"
        typer.echo(f"existing {row['id']} -> {to} ({why}; state {row['state']}); not sent again. "
                   "Track it with st sessions inbox")
        return
    typer.echo(f"sent {row['id']} -> {to}; the recipient's hook shows it on its next turn or wakes it when idle. "
               "Track seen/ack with st sessions inbox")
    if not coord.known_target(to):
        live = ", ".join(coord.live_agents()) or "none"
        typer.echo(f"WARNING {to} is not a registered agent id (cc:/codex:/pi:/agy: id or 13+ char session prefix); "
                   f"it cannot see or ack this. Live agents: {live}", err=True)


def ack(
    message_id: Annotated[str, typer.Argument(help="Request id from st sessions inbox")],
    intent: Annotated[str, typer.Argument(help="yes | no | eta:<minutes>")],
    note: Annotated[str | None, typer.Argument(help="Short neutral reason")] = None,
) -> None:
    """Answer a request addressed to you; 'no' needs a reason, and yes authorizes the requester's --with-ack for 2h.

    An eta whose minutes run out puts the request back to waiting on you: answer yes, no or a new eta.
    """
    try:
        row = coord.ack(message_id, intent, note)
    except ValueError as exc:
        _fail(exc)
        return
    typer.echo(f"acked {row['id']} {intent}")


def confirm(
    message_id: Annotated[str, typer.Argument(help="Request id you sent")],
    withdraw: Annotated[bool, typer.Option("--withdraw", help="Close an unacked request you sent")] = False,
) -> None:
    """Close an acked request you sent (third step of the handshake), or withdraw an unacked one."""
    try:
        coord.confirm(message_id, withdraw=withdraw)
    except ValueError as exc:
        _fail(exc)
        return
    typer.echo(f"{'withdrew' if withdraw else 'closed'} {message_id}")


@usage(
    surface="st.sessions.inbox",
    cmd="st sessions inbox",
    when="see requests waiting for your ack, and the state of requests you sent",
    precautions=("Your sent requests read open/seen (recipient was shown it), open/unseen, or acked; "
                 "close acked ones with st sessions confirm ID",),
    tier="reference",
)
def inbox() -> None:
    """List open coordination requests to and from you; silent when empty.

    A request you sent reads open/seen once the recipient was shown it,
    open/unseen before that, then acked with its reply note; close it with
    st sessions confirm ID.
    """
    for row in coord.inbox():
        detail = row["intent"] or "-"
        if row.get("eta_min"):
            detail += f" {row['eta_min']}m"
        if row.get("note"):
            detail += f" ({row['note']})"
        state = row["state"]
        if state == "open" and row["from"] in leases.self_ids():
            state += "/seen" if coord.surfaced(row) else "/unseen"
        typer.echo(f"{row['id']} {state} {row['from']}->{row['to']} {detail} | {row['text']}")
    for line in coord.notices():
        typer.echo(line)


# The inbox hook also shows memory notices; Nightshift owns that record and its reader.
setattr(inbox, USAGE_SPECS_ATTR, (UsageSpec(
    surface="nightshift.memory.events",
    cmd="nightshift memory events --mine",
    when="a command ended early (exit 137, a pipeline with missing output, a lost background job) or a memory notice "
         "appeared: what Tether's memory guard or the kernel killed in this agent pane, when, and why",
    precautions=(
        "read-only; Nightshift owns the record; --mine also finds kills in an earlier pane this session was resumed out of",
        "other panes or windows: --scope <unit> or --since 2h; --json gives the v1 records",
    ),
    examples=("nightshift memory events --mine --since 2h",),
    task_types=("devops", "debugging"),
    on_demand="host and project troubleshooting",
    tier="reference",
),))


@usage(
    surface="st.sessions.may_disrupt",
    cmd="st sessions may-disrupt [TARGET] [--requests ID,ID]",
    when="before a host-level disruption (reboot, service restart): who is working, replies to your handshakes, "
         "repo holds and leases, running backups, as one JSON answer",
    precautions=("read-only; TARGET is host (default), a project id or a unit; clear stays false while any part "
                 "is unreadable (see unknown); it does not send handshakes",),
    tier="reference",
)
def may_disrupt(
    target: Annotated[str, typer.Argument(help="host (default), a project id, or a unit name")] = "host",
    requests: Annotated[str | None, typer.Option("--requests", help="Comma-separated handshake ids to report; "
                                                 "defaults to every request you sent")] = None,
) -> None:
    """One JSON answer to "may I disrupt TARGET now?": agents, handshake replies, holds, leases, running backups."""
    import json

    from ..client import STClient
    from ..lib import coord_disrupt

    client: STClient | None = None

    def _client() -> STClient:
        nonlocal client
        client = client or STClient(require_project=False)
        return client

    def _sessions() -> list[dict]:
        return _client().list_sessions(status="active", limit=100)

    def _backups() -> list[dict]:
        body = _client().get(_client()._global_url("/backups?status=running&limit=50"))
        return list(body.get("backups") or []) if isinstance(body, dict) else []

    ids = [r.strip() for r in (requests or "").split(",") if r.strip()]
    payload = coord_disrupt.snapshot(target, request_ids=ids, sessions=_sessions, running_backups=_backups)
    typer.echo(json.dumps(payload, indent=2, default=str))


def register(app: typer.Typer) -> None:
    app.command("may-disrupt")(may_disrupt)
    app.command("ack")(ack)
    app.command("confirm")(confirm)
    app.command("inbox")(inbox)
