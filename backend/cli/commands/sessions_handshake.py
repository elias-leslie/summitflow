"""Agent-to-agent request -> ack -> confirm on the shared coordination ledger."""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import quote, urlencode

import typer
from st_sdk.usage import USAGE_SPECS_ATTR, UsageSpec, usage

from ..config import get_config_optional
from ..lib import aico_delegate, coord, coord_remote, leases


def _aico(*argv: str) -> None:
    """Hand the verb to Aico (workstation only: an agent host reaches the workstation's API instead)."""
    if aico_delegate.enabled() and coord_remote.agent_host() is None:
        raise typer.Exit(aico_delegate.run("sessions", *argv))


def _fail(exc: ValueError) -> None:
    typer.echo(f"ERROR {exc}", err=True)
    raise typer.Exit(2)


def _workstation(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call the workstation's coordination API from an agent host (cli/lib/coord_remote.py)."""
    import httpx

    from ..client import APIError, STClient

    client = STClient(require_project=False)
    url = client._global_url(f"/fleet/v1/coordination/requests{path}")
    try:
        return client.post(url, json=body) if method == "POST" else client.get(url)
    except APIError as exc:
        detail = exc.detail.get("message", exc.detail) if isinstance(exc.detail, dict) else exc.detail
        raise ValueError(f"the workstation refused it: {detail}") from exc
    except httpx.HTTPError as exc:
        raise ValueError(f"the workstation's SummitFlow API did not answer ({type(exc).__name__})") from exc


def _host_identity() -> tuple[str, list[str], str | None]:
    """(host, my ledger ids, my window) of an agent on this agent host."""
    from ..lib import coord_remote

    agent_id, window = coord_remote._sender()
    senders = [i for i in dict.fromkeys([agent_id, *sorted(leases.self_ids())]) if coord_remote.SENDER.fullmatch(i)]
    return coord_remote.agent_host() or "", senders, window or None


def _on_workstation(exc: ValueError) -> bool:
    """An agent host's ledger lacks the id: the request may be in the workstation's."""
    from ..lib import coord_remote

    return isinstance(exc, coord.UnknownRequest) and coord_remote.agent_host() is not None


# A bare yes, or a lane's yes to its launcher, closes a request without waking its sender
# (coord_deliver.settle_bare_ack): say how to be woken.
_ACK_WAKE = "If you wait on the answer, arm st aico wait reply {id}: a yes otherwise may reach you without a wake"


def send_request(to: str, text: str, source_key: str | None = None, *, fyi: bool = False) -> None:
    _aico("send", to, text, *(["--source-key", source_key] if source_key else []), *(["--fyi"] if fyi else []))
    cfg = get_config_optional()
    try:
        row = coord.send(to, text, project=getattr(cfg, "project_id", None) or None, source_key=source_key, fyi=fyi)
    except ValueError as exc:
        _fail(exc)
        return
    if row.get("duplicate"):
        why = "same source key" if source_key and row.get("source_key") == source_key else "same open text"
        typer.echo(f"existing {row['id']} -> {to} ({why}; state {row['state']}); not sent again. "
                   "Track it with st sessions inbox")
        return
    from ..lib import coord_deliver

    sender = str(row["from"])
    if fyi:
        coord_deliver.safe_wake(to, [f"{row['id']}:fyi"], sender=sender)
        typer.echo(f"sent FYI {row['id']} -> {to}; it does not wake anyone: the recipient's hook shows it on its next "
                   "turn (or with the next message that does wake it). No ack or confirm needed")
    elif queued := coord_deliver.safe_wake(to, [f"{row['id']}:req"], sender=sender):
        typer.echo(f"sent {row['id']} -> {to}; Tether delivers a [Message] line to its window {queued['widget']} "
                   f"when it is idle (delivery {queued['delivery']['id']}), and its hook shows the request. "
                   f"Track seen/ack with st sessions inbox. {_ACK_WAKE.format(id=row['id'])}")
    else:
        typer.echo(f"sent {row['id']} -> {to}; the recipient's hook shows it on its next turn or wakes it when idle. "
                   f"Track seen/ack with st sessions inbox. {_ACK_WAKE.format(id=row['id'])}")
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
    A yes to a sender not waiting on a reply closes the request for them when it is bare, or comes from the
    sender's own lane: no wake, nothing to confirm; the note rides with their next turn.
    """
    _aico("ack", message_id, intent, *([note] if note else []))
    try:
        row = coord.ack(message_id, intent, note)
    except ValueError as exc:
        if not _on_workstation(exc):
            _fail(exc)
            return
        host, senders, window = _host_identity()
        if not senders:
            _fail(ValueError(f"unknown request {message_id}; this agent has no id the workstation accepts"))
            return
        if not window:
            _fail(ValueError(f"unknown request {message_id}; a request from the workstation is acked from "
                             "the window it was posted into (AICO_WIDGET_ID is not set)"))
            return
        try:
            _workstation("POST", f"/{quote(message_id, safe='')}/ack",
                         {"intent": intent, "note": note, "sender": senders[0], "host": host, "window": window})
        except ValueError as remote_exc:
            _fail(remote_exc)
            return
        typer.echo(f"acked {message_id} {intent} on the workstation")
        return
    from ..lib import coord_deliver

    typer.echo(f"acked {row['id']} {intent}")
    coord_deliver.nudge("reply", row["id"])
    row = coord_deliver.settle_bare_ack(row)
    try:
        if window := coord_remote.post_ack(row):
            typer.echo(f"posted the ack into window {window['id']} on {window['host']}")
            return
    except ValueError as exc:
        typer.echo(f"WARNING the sender's window did not get the ack: {exc}; it sees it in st sessions inbox",
                   err=True)
        return
    queued = coord_deliver.safe_wake(str(row["from"]), [f"{row['id']}:ack:{row.get('acked_at')}"],
                                     sender=str(row.get("acked_by") or ""), reply=True)
    if row.get("auto_closed"):
        typer.echo(f"closed {row['id']}: no confirm needed"
                   + (f"; {row['from']} gets it with its next message or turn, no wake" if queued else ""))
    elif queued:
        typer.echo(f"Tether delivers a [Message] line about the ack to {row['from']}")


def confirm(
    message_id: Annotated[str, typer.Argument(help="Request id you sent")],
    withdraw: Annotated[bool, typer.Option("--withdraw", help="Close an unacked request you sent")] = False,
) -> None:
    """Close an acked request you sent (third step of the handshake), or withdraw an unacked one."""
    _aico("confirm", message_id, *(["--withdraw"] if withdraw else []))
    try:
        coord.confirm(message_id, withdraw=withdraw)
    except ValueError as exc:
        if not _on_workstation(exc):
            _fail(exc)
            return
        host, senders, _ = _host_identity()
        if not senders:
            _fail(ValueError(f"unknown request {message_id}; this agent has no id the workstation accepts"))
            return
        try:
            _workstation("POST", f"/{quote(message_id, safe='')}/confirm",
                         {"senders": senders, "host": host, "withdraw": withdraw})
        except ValueError as remote_exc:
            _fail(remote_exc)
            return
        typer.echo(f"{'withdrew' if withdraw else 'closed'} {message_id} on the workstation")
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
    _aico("inbox")

    def show(row: dict[str, Any], state: str) -> None:
        detail = row["intent"] or "-"
        if row.get("eta_min"):
            detail += f" {row['eta_min']}m"
        if row.get("note"):
            detail += f" ({row['note']})"
        typer.echo(f"{row['id']} {state} {row['from']}->{row['to']} {detail} | {row['text']}")

    for row in coord.inbox():
        state = row["state"]
        if state == "open" and row["from"] in leases.self_ids():
            state += "/seen" if coord.surfaced(row) else "/unseen"
        show(row, state)
    if coord_remote.agent_host() and (identity := _host_identity())[1]:
        host, senders, window = identity
        query = urlencode({"host": host, "sender": senders, **({"window": window} if window else {})}, doseq=True)
        try:
            remote = _workstation("GET", f"?{query}").get("requests") or []
        except ValueError as exc:
            remote = []
            typer.echo(f"WARNING requests on the workstation are not listed: {exc}", err=True)
        for row in remote:
            show(row, f"{row['state']}@workstation")
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
    """One JSON answer to "may I disrupt TARGET now?": agents, handshake replies, holds, leases, running backup units."""
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

    ids = [r.strip() for r in (requests or "").split(",") if r.strip()]
    payload = coord_disrupt.snapshot(target, request_ids=ids, sessions=_sessions)
    typer.echo(json.dumps(payload, indent=2, default=str))


def register(app: typer.Typer) -> None:
    app.command("may-disrupt")(may_disrupt)
    app.command("ack")(ack)
    app.command("confirm")(confirm)
    app.command("inbox")(inbox)
