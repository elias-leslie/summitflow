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
    open/unseen before that, then acked; close it with st sessions confirm ID.
    """
    for row in coord.inbox():
        detail = row["intent"] or "-"
        if row.get("eta_min"):
            detail += f" {row['eta_min']}m"
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
         "appeared: what memctl or the kernel killed in this agent pane, when, and why",
    precautions=(
        "read-only; Nightshift owns the record; --mine also finds kills in an earlier pane this session was resumed out of",
        "other panes or windows: --scope <unit> or --since 2h; --json gives the v1 records",
    ),
    examples=("nightshift memory events --mine --since 2h",),
    task_types=("devops", "debugging"),
    on_demand="host and project troubleshooting",
    tier="reference",
),))


def register(app: typer.Typer) -> None:
    app.command("ack")(ack)
    app.command("confirm")(confirm)
    app.command("inbox")(inbox)
