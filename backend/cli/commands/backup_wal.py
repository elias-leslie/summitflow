"""WAL archiving CLI commands."""

from __future__ import annotations

from typing import Annotated

import typer

from ..output import output_json
from ..output_context import OutputContext

app = typer.Typer(help="WAL archiving management")


@app.callback()
def wal_callback(ctx: typer.Context) -> None:
    """Initialize context if not set."""
    if ctx.obj is None:
        ctx.obj = OutputContext()


@app.command("status")
def wal_status(ctx: typer.Context) -> None:
    """Show WAL archiving status."""
    from app.tasks.backup_wal import get_wal_status

    try:
        status = get_wal_status()
        if ctx.obj.is_compact:
            enabled = "enabled" if status.get("enabled") else "disabled"
            lsn = status.get("current_lsn", "unknown")
            archived = status.get("archived_count", 0)
            failed = status.get("failed_count", 0)
            print(f"WAL {enabled}|lsn:{lsn}|archived:{archived}|failed:{failed}")
        else:
            output_json(status)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None


@app.command("enable")
def wal_enable(
    ctx: typer.Context,
    archive_dir: Annotated[
        str, typer.Option("--dir", help="WAL archive directory")
    ] = "/var/lib/postgresql/wal-archive",
) -> None:
    """Enable WAL archiving."""
    from app.tasks.backup_wal import enable_wal_archiving

    try:
        result = enable_wal_archiving(archive_dir)
        if ctx.obj.is_compact:
            print(f"WAL_ENABLED archive_dir:{archive_dir}")
        else:
            output_json(result)
        typer.echo("Note: archive_mode=on requires a PostgreSQL restart to take full effect.")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None


@app.command("cleanup")
def wal_cleanup(
    ctx: typer.Context,
    retention_days: Annotated[
        int, typer.Option("--retention-days", "-r", help="Delete segments older than N days")
    ] = 7,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show eligible without deleting")] = False,
) -> None:
    """Clean up old WAL archive segments."""
    from app.tasks.backup_wal_cleanup import cleanup_wal_archive

    try:
        result = cleanup_wal_archive(retention_days=retention_days, dry_run=dry_run)
        if ctx.obj.is_compact:
            status = result.get("status", "unknown")
            deleted = result.get("deleted_count", result.get("eligible_count", 0))
            print(f"WAL_CLEANUP {status}|deleted:{deleted}|retention:{retention_days}d")
        else:
            output_json(result)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None


@app.command("disable")
def wal_disable(ctx: typer.Context) -> None:
    """Disable WAL archiving."""
    from app.tasks.backup_wal import disable_wal_archiving

    try:
        result = disable_wal_archiving()
        if ctx.obj.is_compact:
            print("WAL_DISABLED")
        else:
            output_json(result)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None
