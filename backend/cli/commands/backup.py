"""Backup management commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..config import get_config
from ..output import handle_api_error, output_json
from ..output_context import OutputContext
from .backup_api import BackupProjectAPI, BackupSourceAPI
from .backup_formatters import (
    format_size,
    output_backup,
    output_backups,
    output_deleted,
    output_source,
    output_sources,
    output_task_queued,
)

app = typer.Typer(help="Backup management commands")


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
        output_task_queued(ctx.obj, result.get("task_id", "?"))
    except APIError as e:
        handle_api_error(e)


@app.command("restore")
def restore_backup(
    ctx: typer.Context,
    backup_id: Annotated[str, typer.Argument(help="Backup ID to restore")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview without restoring")] = False,
    source: Annotated[str | None, typer.Option("--source", help="Source ID (for non-project restores)")] = None,
) -> None:
    """Restore from a backup. Use --source for non-project sources."""
    try:
        if source:
            result = _get_source_api().restore_source_backup(source, backup_id, dry_run=dry_run)
        else:
            project_api = _get_project_api()
            project_api.get_backup(backup_id)  # validate backup exists
            result = project_api.restore_backup(backup_id, dry_run=dry_run)
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
    """Show most recent backup status."""
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


@app.command("schedule")
def backup_schedule(
    ctx: typer.Context,
    source_id: Annotated[str, typer.Argument(help="Source ID to configure")],
    enable: Annotated[bool | None, typer.Option("--enable/--disable", help="Enable or disable")] = None,
    frequency: Annotated[str | None, typer.Option("--frequency", "-f", help="daily, weekly, monthly")] = None,
    retention_days: Annotated[int | None, typer.Option("--retention-days", "-r", help="Days to retain backups")] = None,
) -> None:
    """View or configure backup schedule for a source."""
    source_api = _get_source_api()
    try:
        if enable is None and frequency is None and retention_days is None:
            source = source_api.get_source(source_id)
            output_source(ctx.obj, source)
        else:
            result = source_api.update_source(
                source_id, enabled=enable, frequency=frequency, retention_days=retention_days
            )
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
        output_backup(ctx.obj, _get_project_api().get_backup(backup_id))
    except APIError as e:
        handle_api_error(e)


@app.command("delete")
def delete_backup(
    ctx: typer.Context,
    backup_id: Annotated[str, typer.Argument(help="Backup ID to delete")],
) -> None:
    """Delete a backup record. Note: Only deletes DB record, not backup files."""
    try:
        _get_project_api().delete_backup(backup_id)
        output_deleted(ctx.obj, backup_id)
    except APIError as e:
        handle_api_error(e)


@app.command("sources")
def list_sources(
    ctx: typer.Context,
    source_type: Annotated[str | None, typer.Option("--type", "-t", help="Filter by type: project, config, workspace")] = None,
) -> None:
    """List all registered backup sources."""
    try:
        sources = _get_source_api().list_sources(source_type=source_type)
        output_sources(ctx.obj, sources)
    except APIError as e:
        handle_api_error(e)
