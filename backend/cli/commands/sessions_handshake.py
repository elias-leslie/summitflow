"""Agent-to-agent request -> ack -> confirm on the shared coordination ledger."""

from __future__ import annotations

from typing import Annotated

import typer
from st_sdk.usage import usage

from ..config import get_config_optional
from ..lib import coord


def _fail(exc: ValueError) -> None:
    typer.echo(f"ERROR {exc}", err=True)
    raise typer.Exit(2)


def send_request(to: str, text: str) -> None:
    cfg = get_config_optional()
    try:
        row = coord.send(to, text, project=getattr(cfg, "project_id", None) or None)
    except ValueError as exc:
        _fail(exc)
        return
    state = "existing" if row.get("duplicate") else "sent"
    typer.echo(f"{state} {row['id']} -> {to}; await ack in st pulse / st sessions inbox")
    if not coord.known_target(to):
        live = ", ".join(coord.live_agents()) or "none"
        typer.echo(f"WARNING {to} is not a registered agent id (cc:/codex:/pi:/agy: id or 13+ char session prefix); "
                   f"it cannot see or ack this. Live agents: {live}", err=True)


@usage(
    surface="st.sessions.ack",
    cmd="st sessions ack ID yes|no|eta:MIN ['short reason']",
    when="answer a coordination request addressed to you; acks are one short line",
    precautions=("'no' needs a reason; yes authorizes the requester's --with-ack for 2h",),
    tier="reference",
)
def ack(
    message_id: Annotated[str, typer.Argument(help="Request id from st sessions inbox")],
    intent: Annotated[str, typer.Argument(help="yes | no | eta:<minutes>")],
    note: Annotated[str | None, typer.Argument(help="Short neutral reason")] = None,
) -> None:
    try:
        row = coord.ack(message_id, intent, note)
    except ValueError as exc:
        _fail(exc)
        return
    typer.echo(f"acked {row['id']} {intent}")


def confirm(message_id: Annotated[str, typer.Argument(help="Request id you sent")]) -> None:
    """Close an acked request you sent (third step of the handshake)."""
    try:
        coord.confirm(message_id)
    except ValueError as exc:
        _fail(exc)
        return
    typer.echo(f"closed {message_id}")


def inbox() -> None:
    """List open coordination requests to and from you; silent when empty."""
    for row in coord.inbox():
        detail = row["intent"] or "-"
        if row.get("eta_min"):
            detail += f" {row['eta_min']}m"
        typer.echo(f"{row['id']} {row['state']} {row['from']}->{row['to']} {detail} | {row['text']}")
    for line in coord.notices():
        typer.echo(line)


def register(app: typer.Typer) -> None:
    app.command("ack")(ack)
    app.command("confirm")(confirm)
    app.command("inbox")(inbox)
