"""Runtime backup command bodies."""

from __future__ import annotations

import typer

from ..client import APIError
from ..lib.confirm_token import confirm_gate
from ..output import handle_api_error, output_error, output_json
from .backup_formatters import output_backup_queue, output_source, output_sources


def backup_all_command(source_api) -> None:
    """Run all-source backup orchestration through the canonical st surface."""
    try:
        queued = 0
        for source in source_api.list_sources():
            source_id = source.get("id")
            if not source_id:
                continue
            result = source_api.create_source_backup(str(source_id))
            queued += 1
            print(f"QUEUED {source_id}|{result.get('task_id') or result.get('message', 'queued')}")
        print(f"BACKUP_ALL queued:{queued}")
    except APIError as e:
        handle_api_error(e)


def restore_backup_id_command(
    ctx,
    *,
    backup_id: str,
    dry_run: bool,
    source: str | None,
    confirm: str | None,
    source_api,
    project_api,
    project_id: str,
) -> None:
    """Restore from a backend backup id."""
    try:
        if not dry_run:
            _confirm_backend_restore(backup_id, source, project_id, confirm)
        result = (
            source_api.restore_source_backup(source, backup_id, dry_run=dry_run)
            if source
            else _restore_project_backup(project_api, backup_id, dry_run)
        )
        _output_restore_result(ctx, result, backup_id=backup_id, source=source, project_id=project_id, dry_run=dry_run)
    except APIError as e:
        handle_api_error(e)


def backup_schedule_command(ctx, source_api, source_id: str, enable: bool | None, frequency: str | None, retention_days: int | None) -> None:
    """View or configure backup schedule for a source."""
    try:
        if enable is None and frequency is None and retention_days is None:
            output_source(ctx.obj, source_api.get_source(source_id))
            return
        result = source_api.update_source(source_id, enabled=enable, frequency=frequency, retention_days=retention_days)
        if ctx.obj.is_compact:
            enabled = "enabled" if result.get("enabled") else "disabled"
            print(f"SCHEDULE_UPDATED {enabled}|{result.get('frequency')}|retention_days:{result.get('retention_days')}")
        else:
            output_json(result)
    except APIError as e:
        handle_api_error(e)


def drain_pending_command(ctx, *, dry_run: bool) -> None:
    """Upload pending backups to SMB and reconcile DB records."""
    from app.tasks.backup_drain import drain_pending_backups

    try:
        result = drain_pending_backups(dry_run=dry_run)
        if ctx.obj.is_compact:
            _print_compact_drain(result)
        else:
            output_json(result)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None


def list_sources_command(ctx, source_api, source_type: str | None) -> None:
    """List all registered backup sources."""
    try:
        sources = source_api.list_sources(source_type=source_type)
        output_sources(ctx.obj, sources)
    except APIError as e:
        handle_api_error(e)


def reject_backup_all_args(args: list[str]) -> None:
    if not args:
        return
    output_error("st backup all does not accept legacy passthrough args; use st backup create/source flags.")
    raise typer.Exit(2) from None


def _confirm_backend_restore(backup_id: str, source: str | None, project_id: str, confirm: str | None) -> None:
    target = f"{source}:{backup_id}" if source else backup_id
    confirm_gate(
        f"backup-restore-{target}",
        confirm,
        [
            f"RESTORE BACKUP: {backup_id}",
            f"Source: {source or project_id}",
            "This can overwrite project files and/or database state.",
            "Use --dry-run first for backend restore preview output.",
        ],
        f"st backup restore {backup_id}{f' --source {source}' if source else ''}",
    )


def _restore_project_backup(project_api, backup_id: str, dry_run: bool) -> dict:
    project_api.get_backup(backup_id)
    return project_api.restore_backup(backup_id, dry_run=dry_run)


def _output_restore_result(
    ctx,
    result: dict,
    *,
    backup_id: str,
    source: str | None,
    project_id: str,
    dry_run: bool,
) -> None:
    task_id = result.get("task_id")
    if task_id:
        print(f"{'DRY_RUN' if dry_run else 'QUEUED'} {task_id}") if ctx.obj.is_compact else output_json(result)
        return
    output_backup_queue(
        ctx.obj,
        status=str(result.get("status", "queued")),
        message=str(result.get("message", "Restore queued")),
        backup_id=backup_id,
        source_id=source,
        project_id=None if source else project_id,
        dry_run=dry_run,
    )


def _print_compact_drain(result: dict) -> None:
    status = result.get("status", "unknown")
    uploaded = result.get("uploaded", 0)
    failed = result.get("failed", 0)
    promoted = result.get("promoted", 0)
    remaining = result.get("remaining", 0)
    db_remaining = result.get("db_remaining", remaining)
    file_remaining = result.get("file_remaining", remaining)
    print(
        f"DRAIN {status}|uploaded:{uploaded}|failed:{failed}|promoted:{promoted}|"
        f"remaining:{remaining}|db_remaining:{db_remaining}|file_remaining:{file_remaining}"
    )
    detail = str(result.get("script_output") or "").strip()
    if detail:
        print(f"DETAIL {detail.splitlines()[0]}")
