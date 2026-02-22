"""Backup management commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..config import get_config
from ..output import handle_api_error, output_error, output_json
from ..output_context import OutputContext
from .backup_api import BackupAPI
from .backup_formatters import (
    format_size,
    output_backup,
    output_backups,
    output_deleted,
    output_schedule,
    output_task_queued,
)

app = typer.Typer(help="Backup management commands")


@app.callback()
def backup_callback(ctx: typer.Context) -> None:
    """Initialize context if not set by parent app."""
    if ctx.obj is None:
        ctx.obj = OutputContext()


def _get_api() -> BackupAPI:
    """Get configured BackupAPI instance."""
    config = get_config()
    client = STClient()
    return BackupAPI(client.base_url, config.project_id)


@app.command("list")
def list_backups(
    ctx: typer.Context,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max results")] = 20,
    status: Annotated[str | None, typer.Option("--status", "-s", help="Filter by status")] = None,
) -> None:
    """List backups for the current project."""
    try:
        result = _get_api().list_backups(limit=limit, status=status)
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
) -> None:
    """Create a new backup for the current project."""
    try:
        result = _get_api().create_backup(note=note, keep_local=keep_local)
        output_task_queued(ctx.obj, result.get("task_id", "?"))
    except APIError as e:
        handle_api_error(e)


@app.command("restore")
def restore_backup(
    ctx: typer.Context,
    backup_id: Annotated[str, typer.Argument(help="Backup ID to restore")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview without restoring")] = False,
) -> None:
    """Restore from a backup. DANGEROUS: This will overwrite current data."""
    api = _get_api()
    try:
        backup = api.get_backup(backup_id)

        result = api.restore_backup(backup_id, dry_run=dry_run)
        if ctx.obj.is_compact:
            print(f"{'DRY_RUN' if dry_run else 'QUEUED'} {result.get('task_id', '?')}")
        else:
            output_json(result)
    except APIError as e:
        handle_api_error(e)


@app.command("status")
def backup_status(
    ctx: typer.Context,
    task_id: Annotated[str | None, typer.Argument(help="Job ID")] = None,
) -> None:
    """Show backup/restore job status. Without task_id, shows most recent backup."""
    if task_id:
        output_error("Task status lookup not yet implemented. Use 'st backup list' instead.")
        raise typer.Exit(1)

    try:
        result = _get_api().list_backups(limit=1)
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


@app.command("schedule")
def backup_schedule(
    ctx: typer.Context,
    enable: Annotated[bool | None, typer.Option("--enable/--disable", help="Enable or disable")] = None,
    frequency: Annotated[str | None, typer.Option("--frequency", "-f", help="daily, weekly, monthly")] = None,
    retention_days: Annotated[int | None, typer.Option("--retention-days", "-r", help="Days to retain backups")] = None,
) -> None:
    """View or configure backup schedule."""
    api = _get_api()
    try:
        if enable is None and frequency is None and retention_days is None:
            output_schedule(ctx.obj, api.get_schedule())
        else:
            result = api.update_schedule(enabled=enable, frequency=frequency, retention_days=retention_days)
            if ctx.obj.is_compact:
                enabled = "enabled" if result.get("enabled") else "disabled"
                print(f"SCHEDULE_UPDATED {enabled}|{result.get('frequency')}|retention_days:{result.get('retention_days')}")
            else:
                output_json(result)
    except APIError as e:
        handle_api_error(e)


@app.command("show")
def show_backup(
    ctx: typer.Context,
    backup_id: Annotated[str, typer.Argument(help="Backup ID")],
) -> None:
    """Show details of a specific backup."""
    try:
        output_backup(ctx.obj, _get_api().get_backup(backup_id))
    except APIError as e:
        handle_api_error(e)


@app.command("delete")
def delete_backup(
    ctx: typer.Context,
    backup_id: Annotated[str, typer.Argument(help="Backup ID to delete")],
) -> None:
    """Delete a backup record. Note: Only deletes DB record, not backup files."""
    try:
        _get_api().delete_backup(backup_id)
        output_deleted(ctx.obj, backup_id)
    except APIError as e:
        handle_api_error(e)
