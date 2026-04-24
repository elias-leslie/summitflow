"""Backup management commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..config import get_config
from ..lib.confirm_token import confirm_gate
from ..output import handle_api_error, output_error, output_json
from ..output_context import OutputContext
from .backup_api import BackupProjectAPI, BackupSourceAPI
from .backup_formatters import (
    format_size,
    output_backup,
    output_backup_queue,
    output_backups,
    output_deleted,
    output_source,
    output_sources,
    output_task_queued,
)
from .backup_infra import app as infra_app
from .backup_storage import app as storage_app
from .backup_testbed import app as testbed_app
from .operator_forward import run_forwarded

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


def _restore_archive_args(
    *,
    latest: bool,
    archive_file: str | None,
    archive_name: str | None,
    dry_run: bool,
    db_only: bool,
    files_only: bool,
) -> list[str]:
    targets = [latest, archive_file is not None, archive_name is not None]
    if sum(1 for target in targets if target) != 1:
        output_error("Use exactly one archive target: --latest, --file PATH, or --name ARCHIVE.")
        raise typer.Exit(1) from None

    args: list[str] = []
    if latest:
        args.append("--latest")
    elif archive_file:
        args.extend(["--file", archive_file])
    elif archive_name:
        args.extend(["--name", archive_name])

    if dry_run:
        args.append("--dry-run")
    if db_only:
        args.append("--db-only")
    if files_only:
        args.append("--files-only")
    return args


def _confirm_restore(
    command_key: str,
    confirm: str | None,
    command_hint: str,
    preview_lines: list[str],
) -> None:
    confirm_gate(command_key, confirm, preview_lines, command_hint)


def _run_archive_restore(
    *,
    latest: bool,
    archive_file: str | None,
    archive_name: str | None,
    dry_run: bool,
    db_only: bool,
    files_only: bool,
    confirm: str | None,
) -> None:
    args = _restore_archive_args(
        latest=latest,
        archive_file=archive_file,
        archive_name=archive_name,
        dry_run=dry_run,
        db_only=db_only,
        files_only=files_only,
    )
    if not dry_run:
        target = "latest" if latest else archive_file or archive_name or "unknown"
        hint = "st backup restore"
        if latest:
            hint += " --latest"
        elif archive_file:
            hint += f" --file {archive_file}"
        elif archive_name:
            hint += f" --name {archive_name}"
        if db_only:
            hint += " --db-only"
        if files_only:
            hint += " --files-only"
        _confirm_restore(
            f"backup-archive-restore-{target}",
            confirm,
            hint,
            [
                f"RESTORE ARCHIVE: {target}",
                "This can overwrite project files and/or database state.",
                "Use --dry-run first for archive restore preview output.",
            ],
        )
    run_forwarded("restore.sh", args)


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
        _run_archive_restore(
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

    try:
        if not dry_run:
            target = f"{source}:{backup_id}" if source else backup_id
            _confirm_restore(
                f"backup-restore-{target}",
                confirm,
                f"st backup restore {backup_id}{f' --source {source}' if source else ''}",
                [
                    f"RESTORE BACKUP: {backup_id}",
                    f"Source: {source or get_config().project_id}",
                    "This can overwrite project files and/or database state.",
                    "Use --dry-run first for backend restore preview output.",
                ],
            )

        if source:
            result = _get_source_api().restore_source_backup(source, backup_id, dry_run=dry_run)
        else:
            project_api = _get_project_api()
            project_api.get_backup(backup_id)  # validate backup exists
            result = project_api.restore_backup(backup_id, dry_run=dry_run)
        task_id = result.get("task_id")
        if task_id:
            if ctx.obj.is_compact:
                print(f"{'DRY_RUN' if dry_run else 'QUEUED'} {task_id}")
            else:
                output_json(result)
        else:
            output_backup_queue(
                ctx.obj,
                status=str(result.get("status", "queued")),
                message=str(result.get("message", "Restore queued")),
                backup_id=backup_id,
                source_id=source,
                project_id=None if source else get_config().project_id,
                dry_run=dry_run,
            )
    except APIError as e:
        handle_api_error(e)


@app.command("status")
def backup_status(
    ctx: typer.Context,
    task_id: Annotated[str | None, typer.Argument(help="Job ID")] = None,
    local: Annotated[bool, typer.Option("--local", help="Show local/SMB archive status")] = False,
) -> None:
    """Show most recent backup status."""
    if local:
        run_forwarded("backup.sh", ["--status"])
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
    run_forwarded("restore.sh", ["--list"])


@app.command("all", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def backup_all(ctx: typer.Context) -> None:
    """Run all-source backup orchestration through the canonical st surface."""
    run_forwarded("backup-all.sh", list(ctx.args))


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
    from app.tasks.backup_drain import drain_pending_backups

    try:
        result = drain_pending_backups(dry_run=dry_run)
        if ctx.obj.is_compact:
            status = result.get("status", "unknown")
            promoted = result.get("promoted", 0)
            remaining = result.get("remaining", 0)
            print(f"DRAIN {status}|promoted:{promoted}|remaining:{remaining}")
        else:
            output_json(result)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None


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
