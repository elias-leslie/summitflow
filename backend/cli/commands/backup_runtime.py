"""Runtime backup command bodies."""

from __future__ import annotations

import hashlib
import hmac
import re
import tempfile
from pathlib import Path
from typing import Any

import typer

from app.tasks.backup_executor import restore_backup_isolated
from app.tasks.backup_native_offsite import decrypt_offsite_archive
from app.tasks.backup_native_restore import restore_isolated_archive

from ..client import APIError
from ..lib.confirm_token import confirm_gate
from ..output import handle_api_error, output_error, output_json
from .backup_formatters import format_size, output_backup_queue, output_source, output_sources


def backup_all_command(source_api, *, storage_backend: str | None = None) -> None:
    """Run all-source backup orchestration through the canonical st surface."""
    try:
        queued = 0
        for source in source_api.list_sources():
            if not source.get("enabled", False):
                continue
            source_id = source.get("id")
            if not source_id:
                continue
            options = {"storage_backend_id": storage_backend} if storage_backend is not None else {}
            result = source_api.create_source_backup(str(source_id), **options)
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


def restore_backup_isolated_command(
    ctx,
    *,
    backup_id: str,
    destination: Path,
    source: str | None,
    archive_file: Path | None,
    remote: bool = False,
    destination_roots: dict[str, Path] | None = None,
) -> None:
    """Restore a checksum-proven backup into an empty isolated directory."""
    try:
        options: dict[str, Any] = {}
        if remote:
            options["remote"] = True
        if destination_roots:
            options["destination_roots"] = destination_roots
        result = restore_backup_isolated(
            backup_id,
            destination,
            expected_source_id=source,
            archive_file=archive_file,
            **options,
        )
    except Exception as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None

    typer.echo("Database dumps are copied for inspection; no database was restored.")
    if result.get("recovery_complete") is False:
        typer.echo("Canonical links are pending: restore their target sources and supply --source-root mappings.")
    if ctx.obj.is_compact:
        typer.echo(
            f"ISOLATED_RESTORE {backup_id}|destination:{destination}|"
            "database_restored:false"
        )
    else:
        output_json(result)


def restore_backup_offline_command(
    ctx,
    *,
    archive_file: Path,
    destination: Path,
    identity_file: Path,
    expected_checksum: str | None,
) -> None:
    """Restore an encrypted archive without API, database, or key-store access."""
    try:
        archive = archive_file.expanduser()
        identity = identity_file.expanduser()
        if not archive.is_file():
            raise FileNotFoundError(f"Backup archive not found: {archive}")
        if not archive.name.endswith(".tar.gz.age"):
            raise RuntimeError("Offline isolated restore requires an encrypted .tar.gz.age archive")
        if not identity.is_file():
            raise FileNotFoundError("Saved age identity file not found")

        with tempfile.TemporaryDirectory(prefix="backup-offline-restore-") as temporary:
            staged_ciphertext = Path(temporary) / archive.name
            actual_checksum = _copy_ciphertext_with_sha256(archive, staged_ciphertext)
            checksum_verified = False
            if expected_checksum is not None:
                normalized = expected_checksum.strip()
                if re.fullmatch(r"sha256:[0-9a-f]{64}", normalized) is None:
                    raise RuntimeError(
                        "Expected checksum must use sha256:<64 lowercase hex characters>"
                    )
                if not hmac.compare_digest(actual_checksum, normalized):
                    raise RuntimeError(
                        "Ciphertext checksum mismatch: refusing offline restore"
                    )
                checksum_verified = True

            plaintext = Path(temporary) / archive.name.removesuffix(".age")
            decrypt_offsite_archive(staged_ciphertext, plaintext, identity)
            plaintext.chmod(0o600)
            restored = restore_isolated_archive(plaintext, destination)
        result = {
            **restored,
            "offline": True,
            "ciphertext_checksum": actual_checksum,
            "ciphertext_checksum_verified": checksum_verified,
        }
    except Exception as exc:
        output_error(str(exc))
        raise typer.Exit(1) from None

    typer.echo("Database dumps are copied for inspection; no database was restored.")
    if checksum_verified:
        typer.echo("Ciphertext SHA-256 matched the supplied external checksum.")
    else:
        typer.echo(
            "No external SHA-256 was supplied; ciphertext integrity was authenticated by age."
        )
    if ctx.obj.is_compact:
        recovery = result.get("recovery")
        git_restored = (
            bool(recovery.get("git_restored")) if isinstance(recovery, dict) else False
        )
        typer.echo(
            f"OFFLINE_ISOLATED_RESTORE {archive.name}|destination:{destination}|"
            f"git_restored:{str(git_restored).lower()}|"
            "database_restored:false"
        )
    else:
        output_json(result)


def _copy_ciphertext_with_sha256(
    source: Path,
    destination: Path,
    *,
    chunk_size: int = 1024 * 1024,
) -> str:
    """Copy ciphertext once into private staging while hashing those exact bytes."""
    digest = hashlib.sha256()
    destination.touch(mode=0o600, exist_ok=False)
    with source.open("rb") as input_file, destination.open("wb") as output_file:
        for chunk in iter(lambda: input_file.read(chunk_size), b""):
            digest.update(chunk)
            output_file.write(chunk)
    return f"sha256:{digest.hexdigest()}"


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


def cleanup_local_command(ctx, *, apply: bool) -> None:
    """Prune expired local backup archive files no longer referenced in DB."""
    from app.tasks.backup_local_cleanup import cleanup_local_backup_archives

    try:
        result = cleanup_local_backup_archives(dry_run=not apply)
        if ctx.obj.is_compact:
            _print_compact_cleanup(result)
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


def _print_compact_cleanup(result: dict) -> None:
    status = result.get("status", "unknown")
    scanned = result.get("scanned", 0)
    candidates = result.get("candidate_count", 0)
    reclaimable = format_size(result.get("bytes_reclaimable"))
    deleted = result.get("deleted", 0)
    deleted_bytes = format_size(result.get("bytes_deleted"))
    failed = result.get("failed", 0)
    print(
        f"LOCAL_BACKUP_CLEANUP {status}|scanned:{scanned}|candidates:{candidates}|"
        f"reclaimable:{reclaimable}|deleted:{deleted}|deleted_bytes:{deleted_bytes}|failed:{failed}"
    )
