"""Btrfs-backed snapshot and recovery commands."""

from __future__ import annotations

from typing import Annotated

import typer

from ..config import get_config
from ..lib.quick_snapshots import (
    SnapshotError,
    capture_snapshot,
    list_snapshots,
    recover_snapshot,
    restore_snapshot,
)
from ..output import output_json
from ..output_context import OutputContext

app = typer.Typer(
    help="Btrfs-backed snapshots and recovery for the current lane or project scope",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)


@app.callback()
def snapshots_callback(ctx: typer.Context) -> None:
    if ctx.obj is None:
        ctx.obj = OutputContext()


def _compact_name(value: str | None) -> str:
    return value or "-"


def _compact_scope(scope_type: str, scope_name: str) -> str:
    return f"{scope_type}:{scope_name}"


@app.command("snap")
def snap_command(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Argument(help="Optional snapshot label")] = None,
) -> None:
    """Capture a Btrfs snapshot for the current lane or project scope."""
    config = get_config()
    try:
        snapshot = capture_snapshot(name, project_id=config.project_id)
    except SnapshotError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None

    if ctx.obj.is_compact:
        print(
            f"SNAP {snapshot.id}|name:{_compact_name(snapshot.name)}|"
            f"scope:{_compact_scope(snapshot.scope_type, snapshot.scope_name)}|"
            f"backend:{snapshot.backend}|branch:{snapshot.branch or 'detached'}"
        )
        return
    output_json(snapshot.to_dict())


@app.command("snaps")
def snaps_command(ctx: typer.Context) -> None:
    """List snapshots for the current lane or project scope."""
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
                f"scope:{_compact_scope(snapshot.scope_type, snapshot.scope_name)}|"
                f"created:{snapshot.created_at}|backend:{snapshot.backend}|"
                f"restored:{snapshot.last_restored_at or '-'}|"
                f"recovered:{snapshot.last_recovered_at or '-'}|usage:shared"
            )
        return
    output_json({"snapshots": [snapshot.to_dict() for snapshot in snapshots], "total": len(snapshots)})


@app.command(
    "recover",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def recover_command(
    ctx: typer.Context,
    target: Annotated[str, typer.Argument(help="Snapshot id, name, or negative index like -1")],
    name: Annotated[
        str | None,
        typer.Option("--name", help="Optional recovery lane or project name"),
    ] = None,
) -> None:
    """Recover a snapshot into a sibling lane or project copy."""
    config = get_config()
    try:
        snapshot = recover_snapshot(target, project_id=config.project_id, name=name)
    except SnapshotError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None

    if ctx.obj.is_compact:
        print(
            f"RECOVERED {snapshot.id}|name:{_compact_name(snapshot.name)}|"
            f"scope:{_compact_scope(snapshot.scope_type, snapshot.scope_name)}|"
            f"path:{snapshot.recovery_path or '-'}|branch:{snapshot.recovery_branch or '-'}"
        )
        return
    output_json(snapshot.to_dict())


@app.command(
    "rollback",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def rollback_command(
    ctx: typer.Context,
    target: Annotated[str, typer.Argument(help="Snapshot id, name, or negative index like -1")],
) -> None:
    """Destructively restore the current task lane to a recorded snapshot."""
    config = get_config()
    try:
        snapshot = restore_snapshot(target, project_id=config.project_id)
    except SnapshotError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None

    if ctx.obj.is_compact:
        print(
            f"ROLLED_BACK {snapshot.id}|name:{_compact_name(snapshot.name)}|"
            f"scope:{_compact_scope(snapshot.scope_type, snapshot.scope_name)}|"
            f"backend:{snapshot.backend}"
        )
        return
    output_json(snapshot.to_dict())
