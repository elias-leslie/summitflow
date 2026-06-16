"""Backup management commands for the CLI."""

from __future__ import annotations

from typing import Annotated

import typer

from ..client import APIError, STClient
from ..config import get_config
from ..lib.usage import usage
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
    cleanup_local_command,
    drain_pending_command,
    list_sources_command,
    reject_backup_all_args,
    restore_backup_id_command,
)
from .backup_storage import app as storage_app
from .backup_testbed import app as testbed_app
from .backup_veeam import app as veeam_app

app = typer.Typer(help="Backup management commands")

# Register sub-command groups
app.add_typer(storage_app, name="storage")
app.add_typer(infra_app, name="infra")
app.add_typer(testbed_app, name="testbed")
app.add_typer(veeam_app, name="veeam")


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
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Preview what would be backed up without queuing an archive")] = False,
) -> None:
    """Create a new backup. Use --source for non-project sources.

    With --dry-run, no archive is created and no server task is queued.
    Instead the local project tree is scanned with the same exclusion
    logic the server uses (DEFAULT_EXCLUDES + .backupignore) and a
    summary is printed: included/excluded file counts, total size, and
    a per-top-level breakdown. Useful for tuning .backupignore before
    running a real backup.
    """
    try:
        if dry_run:
            _create_backup_dry_run(source=source)
            return
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


def _create_backup_dry_run(*, source: str | None) -> None:
    """Local preview of what `st backup create` would archive.

    Mirrors the server-side exclusion logic in
    `app/tasks/backup_native_archive.py` (DEFAULT_EXCLUDES + the
    project's .backupignore) so the dry-run is a faithful preview
    rather than an approximation.

    For project backups, the project root is `config.project_root`
    (or cwd as a fallback). For source backups we don't have a
    project root in the same sense, so we report that the dry-run
    only covers the local view and that the source's actual archive
    is assembled server-side.
    """
    import fnmatch
    from pathlib import Path

    from ..config import get_config

    if source:
        # Source backups are assembled server-side; the local view is
        # only a partial preview. Print a clear note and exit.
        print(f"DRY-RUN SOURCE={source}")
        print("Source backups are assembled server-side from the registered source path.")
        print("Run this from the project that owns the source for a faithful preview.")
        return

    config = get_config()
    project_root = Path(config.project_root or Path.cwd())
    if not project_root.exists():
        print(f"DRY-RUN: project root does not exist: {project_root}")
        return

    # Mirror the server's DEFAULT_EXCLUDES (kept in sync with
    # backup_native_archive.py). If that list grows, update this one.
    patterns = [
        "backend/.venv",
        "frontend/node_modules",
        "frontend/.next",
        ".git",
        ".mypy_cache",
        "backend/.mypy_cache",
        "__pycache__",
        "*.pyc",
        "*.pyo",
        "backend/.ruff_cache",
        ".ruff_cache",
        "backend/.pytest_cache",
        ".pytest_cache",
        "./backups",
        "backups",
        ".tmp",
        ".tmp-*",
        ".claude/backups",
        ".claude/plans",
        "data/artifacts",
        "data/evidence",
        "node_modules",
        "docker/compose/hatchet-config",
    ]

    ignore_file = project_root / ".backupignore"
    if ignore_file.exists():
        for raw in ignore_file.read_text(errors="ignore").splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                patterns.append(line.rstrip("/"))

    def should_exclude(rel_path: str) -> bool:
        normalized = rel_path.removeprefix("./")
        parts = normalized.split("/")
        for pat in patterns:
            p = pat.removeprefix("./").rstrip("/")
            if fnmatch.fnmatch(normalized, p) or fnmatch.fnmatch(Path(normalized).name, p):
                return True
            if any(fnmatch.fnmatch(part, p) for part in parts):
                return True
            if normalized.startswith(f"{p}/"):
                return True
        return False

    import os

    total_files = 0
    excluded_files = 0
    included_files = 0
    excluded_size = 0
    included_size = 0
    included_by_top_level: dict[str, tuple[int, int]] = {}
    excluded_by_top_level: dict[str, tuple[int, int]] = {}

    for root, dirs, files in os.walk(project_root):
        # Mirror the server's hard-coded skip of .git.
        dirs[:] = [d for d in dirs if d != ".git"]
        for fname in files:
            full = Path(root) / fname
            try:
                rel = full.relative_to(project_root).as_posix()
            except ValueError:
                continue
            try:
                size = full.stat().st_size
            except OSError:
                size = 0
            total_files += 1
            top = rel.split("/", 1)[0] if "/" in rel else "(root)"
            if should_exclude(rel):
                excluded_files += 1
                excluded_size += size
                excluded_by_top_level[top] = (
                    excluded_by_top_level.get(top, (0, 0))[0] + 1,
                    excluded_by_top_level.get(top, (0, 0))[1] + size,
                )
            else:
                included_files += 1
                included_size += size
                included_by_top_level[top] = (
                    included_by_top_level.get(top, (0, 0))[0] + 1,
                    included_by_top_level.get(top, (0, 0))[1] + size,
                )

    def fmt(n: int) -> str:
        for u in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.1f}{u}"
            n //= 1024
        return f"{n}TB"

    print(f"DRY-RUN project={project_root}")
    print(f"  total files scanned: {total_files}")
    print(f"  included (will archive): {included_files} files, {fmt(included_size)}")
    print(f"  excluded:                {excluded_files} files, {fmt(excluded_size)}")
    if total_files:
        pct = excluded_files / total_files * 100
        print(f"  excluded fraction:       {pct:.1f}% of files")
    if included_size + excluded_size:
        size_pct = excluded_size / (included_size + excluded_size) * 100
        print(f"  excluded size fraction:  {size_pct:.1f}% of size")
    print()
    print("  Per top-level (included / excluded):")
    all_tops = sorted(set(included_by_top_level) | set(excluded_by_top_level))
    for top in all_tops:
        inc_c, inc_s = included_by_top_level.get(top, (0, 0))
        exc_c, exc_s = excluded_by_top_level.get(top, (0, 0))
        print(f"    {top:<24}  inc={inc_c:>5} ({fmt(inc_s):>8})  exc={exc_c:>5} ({fmt(exc_s):>8})")
    print()
    print("  No archive was created. No server task was queued.")
    print("  To run for real, drop --dry-run.")


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


@app.command("cleanup-local")
@usage(
    surface="st.backup.cleanup-local",
    cmd="st backup cleanup-local",
    when="prune local backup archive files that are older than source retention and no longer referenced by backup DB records",
    precautions=(
        "run without --apply first to preview reclaimable files and bytes",
        "never delete individual Veeam .vbk/.vib files with this command",
        "only configured local project-backup archive roots are scanned",
    ),
    examples=("st backup cleanup-local", "st backup cleanup-local --apply"),
    task_types=("devops", "backup", "cleanup"),
    tier="reference",
)
def cleanup_local(
    ctx: typer.Context,
    apply: Annotated[bool, typer.Option("--apply", help="Delete candidates instead of dry-run preview")] = False,
) -> None:
    """Prune expired local archive files no longer referenced in DB."""
    cleanup_local_command(ctx, apply=apply)


@app.command("sources")
def list_sources(
    ctx: typer.Context,
    source_type: Annotated[str | None, typer.Option("--type", "-t", help="Filter by type: project, config, workspace")] = None,
) -> None:
    """List all registered backup sources."""
    list_sources_command(ctx, _get_source_api(), source_type)
