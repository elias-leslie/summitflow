"""Backup management commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..config import get_config
from ..output import handle_api_error, output_error, output_json
from ..output_context import OutputContext
from .backup_api import BackupProjectAPI, BackupSourceAPI
from .backup_archives import (
    archive_paths,
    list_archives_command,
    local_status_command,
    run_archive_restore,
)
from .backup_formatters import (
    format_size,
    output_backup,
    output_backup_queue,
    output_backups,
    output_deleted,
    output_task_queued,
)
from .backup_infra import app as infra_app
from .backup_runtime import (
    backup_all_command,
    backup_schedule_command,
    drain_pending_command,
    list_sources_command,
    reject_backup_all_args,
    restore_backup_id_command,
)
from .backup_storage import app as storage_app
from .backup_testbed import app as testbed_app

app = typer.Typer(help="Backup management commands")

# Register sub-command groups
app.add_typer(storage_app, name="storage")
app.add_typer(infra_app, name="infra")
app.add_typer(testbed_app, name="testbed")


@app.callback()
def backup_callback(ctx: typer.Context) -> None:
    """Initialize context if not set by parent app."""
    if ctx.obj is None:
        ctx.obj = OutputContext()


def _get_project_api() -> BackupProjectAPI:
    """Get configured BackupProjectAPI instance."""
    config = get_config()
    client = STClient()
    return BackupProjectAPI(client.base_url, config.project_id)


def _get_source_api() -> BackupSourceAPI:
    """Get configured BackupSourceAPI instance."""
    client = STClient()
    return BackupSourceAPI(client.base_url)


@app.command("list")
def list_backups(
    ctx: typer.Context,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max results")] = 20,
    status: Annotated[str | None, typer.Option("--status", "-s", help="Filter by status")] = None,
    source: Annotated[str | None, typer.Option("--source", help="Filter by source ID")] = None,
) -> None:
    """List backups. Use --source to filter by source ID."""
    try:
        if source:
            result = _get_source_api().list_source_backups(source, limit=limit, status=status)
        else:
            result = _get_project_api().list_backups(limit=limit, status=status)
        backups = result.get("backups", [])
        total = result.get("total", len(backups))
        output_backups(ctx.obj, backups, total)
    except APIError as e:
        handle_api_error(e)


@app.command("create")
def create_backup(
    ctx: typer.Context,
    note: Annotated[str | None, typer.Option("--note", "-n", help="Backup note")] = None,
    keep_local: Annotated[bool, typer.Option("--keep-local", help="Keep local copy")] = False,
    source: Annotated[str | None, typer.Option("--source", help="Source ID (for non-project backups)")] = None,
) -> None:
    """Create a new backup. Use --source for non-project sources."""
    try:
        if source:
            result = _get_source_api().create_source_backup(source, note=note, keep_local=keep_local)
        else:
            result = _get_project_api().create_backup(note=note, keep_local=keep_local)
        task_id = result.get("task_id")
        if task_id:
            output_task_queued(ctx.obj, task_id)
        else:
            output_backup_queue(
                ctx.obj,
                status=str(result.get("status", "queued")),
                message=str(result.get("message", "Backup queued")),
                source_id=source,
                project_id=None if source else get_config().project_id,
            )
    except APIError as e:
        handle_api_error(e)


_archive_paths = archive_paths


@app.command("restore")
def restore_backup(
    ctx: typer.Context,
    backup_id: Annotated[str | None, typer.Argument(help="Backup ID to restore")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview without restoring")] = False,
    source: Annotated[str | None, typer.Option("--source", help="Source ID (for non-project restores)")] = None,
    confirm: Annotated[str | None, typer.Option("--confirm", help="Confirm token from preview run")] = None,
    latest: Annotated[bool, typer.Option("--latest", help="Restore latest archive")] = False,
    archive_file: Annotated[str | None, typer.Option("--file", help="Restore archive path")] = None,
    archive_name: Annotated[str | None, typer.Option("--name", help="Restore named archive")] = None,
    db_only: Annotated[bool, typer.Option("--db-only", help="Restore database only for archive restores")] = False,
    files_only: Annotated[bool, typer.Option("--files-only", help="Restore files only for archive restores")] = False,
) -> None:
    """Restore from a backup ID or local/pending/SMB archive."""
    if latest or archive_file or archive_name:
        run_archive_restore(
            latest=latest,
            archive_file=archive_file,
            archive_name=archive_name,
            dry_run=dry_run,
            db_only=db_only,
            files_only=files_only,
            confirm=confirm,
        )
        return

    if db_only or files_only:
        output_error("--db-only and --files-only are only valid with --latest, --file, or --name archive restores.")
        raise typer.Exit(1) from None

    if not backup_id:
        output_error("Backup ID required, or use --latest, --file, or --name for archive restore.")
        raise typer.Exit(1) from None

    restore_backup_id_command(
        ctx,
        backup_id=backup_id,
        dry_run=dry_run,
        source=source,
        confirm=confirm,
        source_api=_get_source_api(),
        project_api=_get_project_api(),
        project_id=get_config().project_id,
    )


@app.command("status")
def backup_status(
    ctx: typer.Context,
    task_id: Annotated[str | None, typer.Argument(help="Job ID")] = None,
    local: Annotated[bool, typer.Option("--local", help="Show local/SMB archive status")] = False,
) -> None:
    """Show most recent backup status."""
    if local:
        local_status_command()
        return

    if task_id:
        from ..output import output_error

        output_error("Task status lookup not yet implemented. Use 'st backup list' instead.")
        raise typer.Exit(1)

    try:
        result = _get_project_api().list_backups(limit=1)
        backups = result.get("backups", [])
        if not backups:
            if ctx.obj.is_compact:
                print("NO_BACKUPS")
            else:
                output_json({"status": "no_backups"})
        else:
            latest = backups[0]
            if ctx.obj.is_compact:
                print(f"LATEST {latest.get('id')}|{latest.get('status')}|{format_size(latest.get('size_bytes'))}")
            else:
                output_json(latest)
    except APIError as e:
        handle_api_error(e)


@app.command("archives")
def list_archives() -> None:
    """List local, pending, and SMB archives."""
    list_archives_command()


@app.command("all", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def backup_all(ctx: typer.Context) -> None:
    """Run all-source backup orchestration through the canonical st surface."""
    reject_backup_all_args(ctx.args)
    backup_all_command(_get_source_api())


@app.command("schedule")
def backup_schedule(
    ctx: typer.Context,
    source_id: Annotated[str, typer.Argument(help="Source ID to configure")],
    enable: Annotated[bool | None, typer.Option("--enable/--disable", help="Enable or disable")] = None,
    frequency: Annotated[str | None, typer.Option("--frequency", "-f", help="daily, weekly, monthly")] = None,
    retention_days: Annotated[int | None, typer.Option("--retention-days", "-r", help="Days to retain backups")] = None,
) -> None:
    """View or configure backup schedule for a source."""
    backup_schedule_command(ctx, _get_source_api(), source_id, enable, frequency, retention_days)


@app.command("show")
def show_backup(
    ctx: typer.Context,
    backup_id: Annotated[str, typer.Argument(help="Backup ID")],
) -> None:
    """Show details of a specific backup."""
    try:
        output_backup(ctx.obj, _get_project_api().get_backup(backup_id))
    except APIError as e:
        handle_api_error(e)


@app.command("delete")
def delete_backup(
    ctx: typer.Context,
    backup_id: Annotated[str, typer.Argument(help="Backup ID to delete")],
    confirm: Annotated[
        str | None,
        typer.Option("--confirm", help="Confirm token from preview run"),
    ] = None,
) -> None:
    """Delete a backup record. Two-pass confirmation required."""
    from ..lib.confirm_token import confirm_gate

    command_key = f"backup-delete-{backup_id}"

    preview_lines: list[str] = []
    if confirm is None:
        try:
            backup = _get_project_api().get_backup(backup_id)
        except APIError as e:
            handle_api_error(e)
            return
        note = backup.get("note", "-") if isinstance(backup, dict) else "-"
        created = backup.get("created_at", "?") if isinstance(backup, dict) else "?"
        preview_lines = [
            f"DELETE BACKUP: {backup_id}",
            f"  Note: {note}",
            f"  Created: {created}",
            "",
            "This will permanently delete the backup record.",
        ]

    confirm_gate(command_key, confirm, preview_lines, f"st backup delete {backup_id}")

    try:
        _get_project_api().delete_backup(backup_id)
        output_deleted(ctx.obj, backup_id)
    except APIError as e:
        handle_api_error(e)


@app.command("drain-pending")
def drain_pending(
    ctx: typer.Context,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show pending without uploading")] = False,
) -> None:
    """Upload pending backups to SMB and reconcile DB records."""
    drain_pending_command(ctx, dry_run=dry_run)


@app.command("sources")
def list_sources(
    ctx: typer.Context,
    source_type: Annotated[str | None, typer.Option("--type", "-t", help="Filter by type: project, config, workspace")] = None,
) -> None:
    """List all registered backup sources."""
    list_sources_command(ctx, _get_source_api(), source_type)
