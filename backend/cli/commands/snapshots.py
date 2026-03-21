"""Btrfs-backed snapshot and recovery commands."""

from __future__ import annotations

from typing import Annotated

import typer

from ..config import get_config
from ..lib.autosnapshot import prune_all
from ..lib.confirm_token import format_preview, generate_token, validate_token
from ..lib.quick_snapshots import (
    SnapshotError,
    capture_snapshot,
    list_snapshots,
    recover_snapshot,
    restore_snapshot,
)
from ..output import output_error, output_json
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
                f"source:{snapshot.source}|"
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
    confirm: Annotated[
        str | None,
        typer.Option("--confirm", help="Confirm token from preview run"),
    ] = None,
) -> None:
    """Destructively restore the current task lane to a recorded snapshot.

    Two-pass confirmation: first run shows what will be replaced,
    second run with --confirm TOKEN executes.
    """
    config = get_config()
    command_key = f"rollback-{config.project_id}-{target}"

    if confirm is None:
        # First pass: preview
        try:
            snapshots = list_snapshots(project_id=config.project_id)
            from ..lib.quick_snapshots import _find_snapshot, _resolve_repo_root, resolve_scope

            repo_root = _resolve_repo_root()
            scope = resolve_scope(repo_root, config.project_id)
            snapshot = _find_snapshot(target, snapshots)
        except SnapshotError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1) from None

        lines = [
            f"ROLLBACK will destructively replace lane: {scope.scope_name}",
            f"  Snapshot: {snapshot.id}",
            f"  Name: {_compact_name(snapshot.name)}",
            f"  Created: {snapshot.created_at}",
            f"  Branch: {snapshot.branch or 'detached'}",
            f"  HEAD: {snapshot.head_oid or '?'}",
            "",
            "Current lane contents will be permanently destroyed.",
            "Consider 'st recover' instead for non-destructive restoration.",
        ]
        token = generate_token(command_key)
        print(format_preview(f"st rollback {target}", lines, token))
        raise typer.Exit(0)

    # Second pass: validate and execute
    if not validate_token(command_key, confirm):
        output_error(
            "Invalid or expired confirm token.\n"
            f"  Run `st rollback {target}` to preview and get a new token."
        )
        raise typer.Exit(1)

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


@app.command("prune")
def prune_command(
    ctx: typer.Context,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would be pruned without deleting"),
    ] = False,
) -> None:
    """Remove old auto snapshots per retention policy."""
    results = prune_all(dry_run=dry_run)
    if not results:
        if ctx.obj.is_compact:
            print("PRUNE[0] nothing to prune")
        else:
            output_json({"pruned": {}, "total": 0})
        return

    total = sum(len(v) for v in results.values())
    if ctx.obj.is_compact:
        action = "would prune" if dry_run else "pruned"
        print(f"PRUNE[{total}] {action}")
        for scope_key, entries in results.items():
            for entry in entries:
                print(
                    f"  {entry.id}|source:{entry.source}|"
                    f"scope:{scope_key}|created:{entry.created_at}"
                )
    else:
        output_json({
            "pruned": {
                k: [e.to_dict() for e in v] for k, v in results.items()
            },
            "total": total,
            "dry_run": dry_run,
        })
