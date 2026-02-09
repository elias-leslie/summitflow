"""Backup management commands for the CLI."""

from __future__ import annotations

from typing import Annotated, Any

import typer

from ..client import APIError, STClient
from ..config import get_config
from ..output import handle_api_error, output_error, output_json
from ..output_context import OutputContext

app = typer.Typer(help="Backup management commands")


@app.callback()
def backup_callback(ctx: typer.Context) -> None:
    """Initialize context if not set by parent app."""
    if ctx.obj is None:
        ctx.obj = OutputContext()


def _format_size(size_bytes: int | None) -> str:
    """Format bytes to human readable."""
    if size_bytes is None or size_bytes == 0:
        return "-"
    size: float = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def _format_compact_backup(backup: dict[str, Any]) -> str:
    """Format backup as compact one-liner.

    Format: <id> <status:9> <size:8> <created> <note:30>
    """
    backup_id = backup.get("id", "?")
    status = (backup.get("status") or "pending")[:9].ljust(9)
    size = _format_size(backup.get("size_bytes"))[:8].ljust(8)
    created = backup.get("created_at", "")[:10]  # Just date
    note = (backup.get("note") or "-")[:30]
    return f"{backup_id} {status} {size} {created} {note}"


def _output_backups(out: OutputContext, backups: list[dict[str, Any]], total: int) -> None:
    """Output backup list."""
    if out.is_compact:
        print(f"BACKUPS[{total}]")
        for b in backups:
            print(_format_compact_backup(b))
    else:
        output_json({"backups": backups, "total": total})


@app.command("list")
def list_backups(
    ctx: typer.Context,
    limit: Annotated[int, typer.Option("--limit", "-l", help="Max results")] = 20,
    status: Annotated[str | None, typer.Option("--status", "-s", help="Filter by status")] = None,
) -> None:
    """List backups for the current project.

    Examples:
        st backup list
        st --compact backup list
        st backup list --status completed
    """
    config = get_config()
    client = STClient()

    try:
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        result = client.get(
            f"{client.base_url}/projects/{config.project_id}/backups?limit={limit}"
            + (f"&status={status}" if status else "")
        )
        backups = result.get("backups", [])
        total = result.get("total", len(backups))
        _output_backups(ctx.obj, backups, total)
    except APIError as e:
        handle_api_error(e)


@app.command("create")
def create_backup(
    ctx: typer.Context,
    note: Annotated[str | None, typer.Option("--note", "-n", help="Backup note")] = None,
    keep_local: Annotated[bool, typer.Option("--keep-local", help="Keep local copy")] = False,
) -> None:
    """Create a new backup for the current project.

    Examples:
        st backup create
        st backup create --note "Before refactor"
        st backup create -n "Pre-deploy snapshot"
    """
    config = get_config()
    client = STClient()

    try:
        import httpx

        data = {"note": note, "keep_local": keep_local}
        response = httpx.post(
            f"{client.base_url}/projects/{config.project_id}/backups",
            json=data,
            timeout=30.0,
        )
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise APIError(response.status_code, detail)
        result = response.json()
        if ctx.obj.is_compact:
            print(f"QUEUED {result.get('task_id', '?')}")
        else:
            output_json(result)
    except APIError as e:
        handle_api_error(e)


@app.command("restore")
def restore_backup(
    ctx: typer.Context,
    backup_id: Annotated[str, typer.Argument(help="Backup ID to restore")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview without restoring")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
) -> None:
    """Restore from a backup.

    DANGEROUS: This will overwrite current data.
    Requires confirmation unless --yes is passed.

    Examples:
        st backup restore bkp-abc123
        st backup restore bkp-abc123 --dry-run
        st backup restore bkp-abc123 --yes
    """
    config = get_config()
    client = STClient()

    try:
        # Get backup info first
        import httpx

        backup_response = httpx.get(
            f"{client.base_url}/projects/{config.project_id}/backups/{backup_id}",
            timeout=30.0,
        )
        if backup_response.status_code >= 400:
            try:
                detail = backup_response.json().get("detail", backup_response.text)
            except Exception:
                detail = backup_response.text
            raise APIError(backup_response.status_code, detail)
        backup = backup_response.json()

        if not dry_run and not yes:
            print(f"About to restore from backup: {backup.get('name', backup_id)}")
            print(f"  Project: {config.project_id}")
            print(f"  Created: {backup.get('created_at', '?')}")
            print(f"  Size: {_format_size(backup.get('size_bytes'))}")
            print()
            confirm = typer.prompt(
                f"Type '{config.project_id}' to confirm restore",
            )
            if confirm != config.project_id:
                output_error("Restore cancelled - confirmation did not match")
                raise typer.Exit(1)

        # Do restore
        response = httpx.post(
            f"{client.base_url}/projects/{config.project_id}/backups/{backup_id}/restore",
            json={"dry_run": dry_run},
            timeout=30.0,
        )
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise APIError(response.status_code, detail)
        result = response.json()

        if ctx.obj.is_compact:
            if dry_run:
                print(f"DRY_RUN {result.get('task_id', 'OK')}")
            else:
                print(f"QUEUED {result.get('task_id', '?')}")
        else:
            output_json(result)
    except APIError as e:
        handle_api_error(e)


@app.command("status")
def backup_status(
    ctx: typer.Context,
    task_id: Annotated[str | None, typer.Argument(help="Job ID")] = None,
) -> None:
    """Show backup/restore job status.

    Without task_id, shows most recent backup status.

    Examples:
        st backup status
        st backup status abc123-task-id
    """
    config = get_config()
    client = STClient()

    try:
        if task_id:
            # Would need task status endpoint - for now show backup list
            output_error("Task status lookup not yet implemented. Use 'st backup list' instead.")
            raise typer.Exit(1)
        else:
            # Show latest backup status
            result = client.get(f"{client.base_url}/projects/{config.project_id}/backups?limit=1")
            backups = result.get("backups", [])
            if not backups:
                if ctx.obj.is_compact:
                    print("NO_BACKUPS")
                else:
                    output_json({"status": "no_backups"})
            else:
                latest = backups[0]
                if ctx.obj.is_compact:
                    print(
                        f"LATEST {latest.get('id')}|{latest.get('status')}|{_format_size(latest.get('size_bytes'))}"
                    )
                else:
                    output_json(latest)
    except APIError as e:
        handle_api_error(e)


@app.command("schedule")
def backup_schedule(
    ctx: typer.Context,
    enable: Annotated[
        bool | None, typer.Option("--enable/--disable", help="Enable or disable")
    ] = None,
    frequency: Annotated[
        str | None, typer.Option("--frequency", "-f", help="daily, weekly, monthly")
    ] = None,
    retention: Annotated[
        int | None, typer.Option("--retention", "-r", help="Backups to retain")
    ] = None,
) -> None:
    """View or configure backup schedule.

    Without options, shows current schedule.
    With options, updates schedule configuration.

    Examples:
        st backup schedule
        st backup schedule --enable --frequency daily
        st backup schedule --disable
        st backup schedule --frequency weekly --retention 10
    """
    config = get_config()
    client = STClient()

    try:
        import httpx

        if enable is None and frequency is None and retention is None:
            # Show current schedule
            response = httpx.get(
                f"{client.base_url}/projects/{config.project_id}/backups/schedule",
                timeout=30.0,
            )
            if response.status_code == 404 or response.text == "null":
                if ctx.obj.is_compact:
                    print("SCHEDULE disabled")
                else:
                    output_json({"enabled": False, "message": "No schedule configured"})
            elif response.status_code >= 400:
                try:
                    detail = response.json().get("detail", response.text)
                except Exception:
                    detail = response.text
                raise APIError(response.status_code, detail)
            else:
                schedule = response.json()
                if ctx.obj.is_compact:
                    enabled = "enabled" if schedule.get("enabled") else "disabled"
                    freq = schedule.get("frequency", "?")
                    ret = schedule.get("retention_count", "?")
                    next_run = (schedule.get("next_run_at") or "?")[:10]
                    print(f"SCHEDULE {enabled}|{freq}|retention:{ret}|next:{next_run}")
                else:
                    output_json(schedule)
        else:
            # Update schedule
            # Get current to preserve values
            current_response = httpx.get(
                f"{client.base_url}/projects/{config.project_id}/backups/schedule",
                timeout=30.0,
            )
            current: dict[str, Any] = {}
            if current_response.status_code == 200 and current_response.text != "null":
                current = current_response.json() or {}

            data = {
                "enabled": enable if enable is not None else current.get("enabled", False),
                "frequency": frequency if frequency else current.get("frequency", "daily"),
                "retention_count": retention
                if retention is not None
                else current.get("retention_count", 5),
            }

            response = httpx.put(
                f"{client.base_url}/projects/{config.project_id}/backups/schedule",
                json=data,
                timeout=30.0,
            )
            if response.status_code >= 400:
                try:
                    detail = response.json().get("detail", response.text)
                except Exception:
                    detail = response.text
                raise APIError(response.status_code, detail)
            result = response.json()

            if ctx.obj.is_compact:
                enabled = "enabled" if result.get("enabled") else "disabled"
                print(
                    f"SCHEDULE_UPDATED {enabled}|{result.get('frequency')}|retention:{result.get('retention_count')}"
                )
            else:
                output_json(result)
    except APIError as e:
        handle_api_error(e)


@app.command("show")
def show_backup(
    ctx: typer.Context,
    backup_id: Annotated[str, typer.Argument(help="Backup ID")],
) -> None:
    """Show details of a specific backup.

    Examples:
        st backup show bkp-abc123
    """
    config = get_config()
    client = STClient()

    try:
        import httpx

        response = httpx.get(
            f"{client.base_url}/projects/{config.project_id}/backups/{backup_id}",
            timeout=30.0,
        )
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise APIError(response.status_code, detail)
        backup = response.json()

        if ctx.obj.is_compact:
            print(_format_compact_backup(backup))
        else:
            output_json(backup)
    except APIError as e:
        handle_api_error(e)


@app.command("delete")
def delete_backup(
    ctx: typer.Context,
    backup_id: Annotated[str, typer.Argument(help="Backup ID to delete")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
) -> None:
    """Delete a backup record.

    Note: Only deletes the database record, not the actual backup files.

    Examples:
        st backup delete bkp-abc123
        st backup delete bkp-abc123 --yes
    """
    config = get_config()
    client = STClient()

    if not yes:
        confirm = typer.confirm(f"Delete backup {backup_id}?")
        if not confirm:
            output_error("Cancelled")
            raise typer.Exit(1)

    try:
        import httpx

        response = httpx.delete(
            f"{client.base_url}/projects/{config.project_id}/backups/{backup_id}",
            timeout=30.0,
        )
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise APIError(response.status_code, detail)
        result = response.json()

        if ctx.obj.is_compact:
            print(f"DELETED {backup_id}")
        else:
            output_json(result)
    except APIError as e:
        handle_api_error(e)
