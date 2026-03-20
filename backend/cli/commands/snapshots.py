"""Fast per-worktree snapshot commands."""

from __future__ import annotations

from typing import Annotated

import typer

from ..config import get_config
from ..lib.quick_snapshots import SnapshotError, capture_snapshot, list_snapshots, restore_snapshot
from ..output import output_json
from ..output_context import OutputContext

app = typer.Typer(
    help="Fast per-worktree snapshots backed by hidden Git refs",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)


@app.callback()
def snapshots_callback(ctx: typer.Context) -> None:
    if ctx.obj is None:
        ctx.obj = OutputContext()


def _compact_name(value: str | None) -> str:
    return value or "-"


@app.command("snap")
def snap_command(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Argument(help="Optional snapshot label")] = None,
) -> None:
    """Capture a fast snapshot for the current worktree lane."""
    config = get_config()
    try:
        snapshot = capture_snapshot(name, project_id=config.project_id)
    except SnapshotError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None

    if ctx.obj.is_compact:
        print(
            f"SNAP {snapshot.id}|name:{_compact_name(snapshot.name)}|"
            f"backend:{snapshot.backend}|branch:{snapshot.branch or 'detached'}"
        )
        return
    output_json(snapshot.to_dict())


@app.command("snaps")
def snaps_command(ctx: typer.Context) -> None:
    """List snapshots for the current worktree lane."""
    config = get_config()
    try:
        snapshots = list_snapshots(project_id=config.project_id)
    except SnapshotError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None

    if ctx.obj.is_compact:
        print(f"SNAPS[{len(snapshots)}]")
        for index, snapshot in enumerate(snapshots, start=1):
            print(
                f"SNAP {index}|{snapshot.id}|name:{_compact_name(snapshot.name)}|"
                f"created:{snapshot.created_at}|backend:{snapshot.backend}|"
                f"restored:{snapshot.last_restored_at or '-'}|usage:shared"
            )
        return
    output_json({"snapshots": [snapshot.to_dict() for snapshot in snapshots], "total": len(snapshots)})


@app.command(
    "rollback",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def rollback_command(
    ctx: typer.Context,
    target: Annotated[str, typer.Argument(help="Snapshot id, name, or negative index like -1")],
) -> None:
    """Restore the current worktree lane to a recorded snapshot."""
    config = get_config()
    try:
        snapshot = restore_snapshot(target, project_id=config.project_id)
    except SnapshotError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None

    if ctx.obj.is_compact:
        print(
            f"ROLLED_BACK {snapshot.id}|name:{_compact_name(snapshot.name)}|"
            f"backend:{snapshot.backend}"
        )
        return
    output_json(snapshot.to_dict())
