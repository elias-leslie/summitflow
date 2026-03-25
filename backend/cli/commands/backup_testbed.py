"""Git-aware backup/reset workflow for resettable testbed projects."""

from __future__ import annotations

from typing import Annotated

import typer

from ..config import get_config
from ..lib.confirm_token import confirm_gate
from ..lib.testbed_backups import (
    TestbedBackupError,
    capture_testbed_baseline,
    preview_testbed_reset,
    reset_testbed_to_baseline,
)
from ..output import output_json
from ..output_context import OutputContext

app = typer.Typer(help="Capture and restore git-aware testbed baselines")


@app.callback()
def backup_testbed_callback(ctx: typer.Context) -> None:
    if ctx.obj is None:
        ctx.obj = OutputContext()


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


@app.command("baseline")
def baseline_command(
    ctx: typer.Context,
    note: Annotated[str | None, typer.Option("--note", "-n", help="Optional baseline note")] = None,
    snapshot_name: Annotated[
        str | None,
        typer.Option("--snapshot-name", help="Optional Btrfs snapshot label"),
    ] = None,
    allow_dirty: Annotated[
        bool,
        typer.Option("--allow-dirty", help="Allow capturing a baseline from a dirty repo"),
    ] = False,
    local_only: Annotated[
        bool,
        typer.Option(
            "--local/--remote",
            help="Store the testbed baseline locally by default; use --remote to use the normal upload path",
        ),
    ] = True,
    keep_local: Annotated[
        bool,
        typer.Option("--keep-local", help="Keep the archive locally in addition to remote storage"),
    ] = False,
) -> None:
    """Capture a testbed baseline backed by both Btrfs and the backup archive flow."""
    config = get_config()
    try:
        result = capture_testbed_baseline(
            config.project_id,
            note=note,
            snapshot_name=snapshot_name,
            allow_dirty=allow_dirty,
            keep_local=keep_local,
            local_only=local_only,
        )
    except TestbedBackupError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None

    if ctx.obj.is_compact:
        print(
            f"TESTBED_BASELINE {result['backup_id']}|snapshot:{result['snapshot_id']}|"
            f"branch:{result['git_branch'] or 'detached'}|head:{result['git_head'] or '?'}|"
            f"dirty:{_yes_no(bool(result['git_dirty']))}"
        )
        return
    output_json(result)


@app.command("reset")
def reset_command(
    ctx: typer.Context,
    backup_id: Annotated[
        str | None,
        typer.Argument(help="Optional backup ID. Defaults to the latest marked testbed baseline"),
    ] = None,
    rebuild: Annotated[
        bool,
        typer.Option("--rebuild/--no-rebuild", help="Run rebuild.sh <project> after reset"),
    ] = True,
    confirm: Annotated[
        str | None,
        typer.Option("--confirm", help="Confirm token from preview run"),
    ] = None,
) -> None:
    """Reset the current project to a previously captured testbed baseline."""
    config = get_config()
    command_key = f"backup-testbed-reset-{config.project_id}-{backup_id or 'latest'}-{rebuild}"

    preview_lines: list[str] = []
    if confirm is None:
        try:
            preview = preview_testbed_reset(config.project_id, backup_id)
        except TestbedBackupError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1) from None

        preview_lines = [
            f"RESET TESTBED PROJECT: {preview['project_id']}",
            f"  Backup: {preview['backup_id']}",
            f"  Archive: {preview['backup_name'] or '-'}",
            f"  Snapshot: {preview['snapshot_id']} ({preview['snapshot_name'] or '-'})",
            f"  Project root: {preview['project_root']}",
            f"  Branch: {preview['git_branch'] or 'detached'}",
            f"  HEAD: {preview['git_head'] or '?'}",
            f"  Database restore: {_yes_no(bool(preview['has_database']))}",
            f"  Rebuild after reset: {_yes_no(rebuild)}",
            "",
            "This will replace the current project files and Git state with the recorded baseline.",
            "If the backup contains a database dump, the project database will also be restored.",
        ]

    command = "st backup testbed reset"
    if backup_id:
        command += f" {backup_id}"
    if not rebuild:
        command += " --no-rebuild"
    confirm_gate(command_key, confirm, preview_lines, command)

    try:
        result = reset_testbed_to_baseline(
            config.project_id,
            backup_id,
            rebuild=rebuild,
        )
    except TestbedBackupError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None

    if ctx.obj.is_compact:
        print(
            f"TESTBED_RESET {result['backup_id']}|snapshot:{result['snapshot_id']}|"
            f"db:{_yes_no(bool(result['db_restored']))}|files:{_yes_no(bool(result['files_restored']))}|"
            f"rebuild:{_yes_no(bool(result['rebuild_ran']))}"
        )
        return
    output_json(result)
