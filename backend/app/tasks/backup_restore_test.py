"""Restore validation testing — dry-run restores to verify backup integrity."""

from __future__ import annotations

import gzip
import subprocess
import tarfile
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from ..storage import backups as backup_store
from ..utils.transient_scratch import (
    ScratchError,
    disposable_scratch,
    ensure_scratch_capacity,
    mounted_scratch_parent,
    scratch_subprocess_env,
    validate_temp_parent,
)
from .backup_activity import BackupCancelled, run_bulk_process
from .backup_coverage import verify_archive_coverage
from .backup_native_restore import materialize_plaintext_archive
from .backup_restore import restore_backup

logger = get_logger(__name__)


def run_restore_test_for_source(source_id: str) -> dict[str, Any]:
    """Run a dry-run restore of the latest backup for a source and record the result.

    For infrastructure sources (no project dir), verifies the archive is
    accessible on SMB and passes integrity check instead of running a file restore.

    Args:
        source_id: Backup source ID to test.

    Returns:
        Test result dict with ok, source_id, error (if any).
    """
    logger.info("restore_test_started", source_id=source_id)

    source = backup_store.get_source(source_id)
    if not source:
        error = f"Source {source_id} not found"
        logger.error("restore_test_source_not_found", source_id=source_id)
        return {"ok": False, "source_id": source_id, "error": error}

    latest = backup_store.get_latest_backup(source_id=source_id)
    if not latest:
        error = f"No completed backups found for source {source_id}"
        backup_store.update_source_restore_test(source_id, ok=False, error=error)
        logger.warning("restore_test_no_backups", source_id=source_id)
        return {"ok": False, "source_id": source_id, "error": error}

    source_type = str(source.get("source_type", ""))
    backup_id = latest["id"]

    # Infrastructure sources don't have a project dir — validate archive coverage instead
    if source_type == "infrastructure":
        return _validate_infra_archive(source_id, latest)

    project_id = str(source.get("project_id") or source_id)

    try:
        result = restore_backup(
            project_id=project_id,
            backup_id=backup_id,
            dry_run=True,
            source_id=source_id,
        )
    except BackupCancelled:
        raise
    except Exception as e:
        error = str(e)
        backup_store.update_source_restore_test(source_id, ok=False, error=error)
        logger.error("restore_test_exception", source_id=source_id, error=error[:200])
        return {"ok": False, "source_id": source_id, "backup_id": backup_id, "error": error}

    ok = result.get("status") == "completed"
    error = result.get("error") if not ok else None
    backup_store.update_source_restore_test(source_id, ok=ok, error=error)

    logger.info("restore_test_completed", source_id=source_id, ok=ok)
    return {
        "ok": ok,
        "source_id": source_id,
        "backup_id": backup_id,
        "error": error,
    }


def _validate_infra_archive(source_id: str, backup: dict[str, Any]) -> dict[str, Any]:
    """Validate an infrastructure backup archive with per-component coverage checks.

    Locates the archive (local, pending, or SMB), then:
    1. Verifies tar integrity
    2. Checks coverage contract (required files present)
    3. Validates pg_dumpall header (SQL)
    4. Validates Redis RDB header (REDIS magic bytes)
    """
    backup_id = backup["id"]
    location = str(backup.get("location") or "")
    name = str(backup.get("name") or "")
    verification_json = backup.get("verification_json")

    archive_staging = ExitStack()
    try:
        archive_path = _locate_archive(location, name, source_id, scratch_stack=archive_staging)
        if archive_path is None:
            raise RuntimeError(f"Cannot locate archive: location={location}, name={name}")
        with materialize_plaintext_archive(Path(archive_path)) as plaintext_archive:
            # 1. Tar integrity
            result = subprocess.run(
                ["tar", "tzf", str(plaintext_archive)],
                capture_output=True,
                text=True,
                timeout=120,
                env=scratch_subprocess_env(),
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"Archive integrity check failed: {result.stderr[:200]}"
                )
            file_listing = result.stdout.strip().splitlines()

            # 2. Coverage contract check
            coverage_result = verify_archive_coverage(verification_json)
            coverage_ok = coverage_result.complete

            # 3. Validate pg_dumpall header (quick sanity check)
            pg_ok = _validate_pgdump_header(str(plaintext_archive))

            # 4. Validate Redis RDB header
            redis_ok = _validate_redis_header(str(plaintext_archive))

            errors: list[str] = []
            if not coverage_ok:
                errors.append(f"Missing required components: {', '.join(coverage_result.missing)}")
            if not pg_ok:
                errors.append("PostgreSQL dump header validation failed")
            if not redis_ok and _has_file_in_listing(file_listing, "redis-dump.rdb"):
                errors.append("Redis RDB header validation failed")

            all_ok = coverage_ok and pg_ok
    except BackupCancelled:
        raise
    except Exception as e:
        error = str(e)
        backup_store.update_source_restore_test(source_id, ok=False, error=error)
        return {"ok": False, "source_id": source_id, "backup_id": backup_id, "error": error}
    finally:
        archive_staging.close()

    backup_store.update_source_restore_test(source_id, ok=all_ok, error="; ".join(errors) if errors else None)

    logger.info("restore_test_completed", source_id=source_id, ok=all_ok, files=len(file_listing),
                coverage_complete=coverage_ok, pg_ok=pg_ok, redis_ok=redis_ok)
    return {
        "ok": all_ok,
        "source_id": source_id,
        "backup_id": backup_id,
        "files": len(file_listing),
        "coverage": {
            "complete": coverage_result.complete,
            "required": coverage_result.required_count,
            "present": coverage_result.present_count,
            "missing": coverage_result.missing,
        },
        "pg_header_ok": pg_ok,
        "redis_header_ok": redis_ok,
        "errors": errors if errors else None,
    }


def _locate_archive(location: str, name: str, source_id: str, *, scratch_stack: ExitStack | None = None) -> str | None:
    """Find the archive file locally, in pending dir, or download from SMB."""
    # Local file
    if location and not location.startswith("//") and Path(location).exists():
        return location

    # Pending dir
    pending_path = Path.home() / ".local" / "share" / "backup-pending" / name
    if name and pending_path.exists():
        return str(pending_path)

    # SMB — download to temp
    smb_path = None
    if location.startswith("//"):
        smb_path = location
    elif name:
        import os
        smb_host = os.environ.get("SMB_HOST", "")
        smb_share = os.environ.get("SMB_SHARE", "")
        if smb_host and smb_share:
            smb_path = f"//{smb_host}/{smb_share}/project-backups/{source_id}/{name}"

    if smb_path:
        destination = scratch_stack.enter_context(disposable_scratch("backup-infra-validation-", namespace="st-restores")) if scratch_stack else None
        return _download_smb_archive(smb_path, destination=destination)

    return None


def _download_smb_archive(smb_path: str, *, destination: Path | None = None) -> str | None:
    """Download an archive from SMB to a temp file. Returns local path or None."""
    import os
    import shutil
    import tempfile

    from app.utils.smb_commands import SmbCommandError, smb_archive_location, smb_command

    creds_file = Path(os.environ.get("HOME", str(Path.home()))) / ".smbcredentials"
    try:
        service, remote_dir, filename = smb_archive_location(smb_path)
    except SmbCommandError:
        return None

    created_here = destination is None
    if destination is None:
        parent = mounted_scratch_parent("st-restores")
        assert parent is not None
        ensure_scratch_capacity(parent, 0)
        destination = Path(tempfile.mkdtemp(prefix="backup-infra-validation-", dir=parent))
    temp_path = destination / filename
    download_env = None if created_here else scratch_subprocess_env(path=destination)
    downloaded = False
    try:
        if created_here:
            download_env = scratch_subprocess_env(path=destination)
        cmd = [
            "smbclient", service, "-A", str(creds_file),
            "-c", smb_command(("cd", remote_dir), ("get", filename, str(temp_path))),
        ]
        result = run_bulk_process(cmd, timeout=300, phase="verification",
                                  env=download_env,
                                  capacity_check=lambda: ensure_scratch_capacity(destination, 0))
        if result.returncode == 0 and temp_path.exists():
            temp_path.chmod(0o600)
            ensure_scratch_capacity(destination, 0)
            downloaded = True
            return str(temp_path)
    except (BackupCancelled, ScratchError):
        raise
    except Exception:
        pass
    finally:
        if created_here and not downloaded:
            shutil.rmtree(temp_path.parent, ignore_errors=True)
    return None


def _cleanup_temp_archive(archive_path: str, original_location: str) -> None:
    """Remove temp archive if it was downloaded from SMB."""
    import shutil
    parent = Path(archive_path).parent
    expected = mounted_scratch_parent("st-restores")
    if parent.parent == expected and parent.name.startswith("backup-infra-validation-"):
        validate_temp_parent(parent, private=True)
        shutil.rmtree(parent)


def _has_file_in_listing(file_listing: list[str], pattern: str) -> bool:
    """Check if any file in the tar listing matches a pattern."""
    return any(pattern in f for f in file_listing)


def _read_unique_archive_member_prefix(
    archive_path: str,
    basename: str,
    byte_count: int,
    *,
    gzip_compressed: bool = False,
) -> bytes | None:
    """Read a bounded prefix from one regular archive member without a shell."""
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            matches = [
                member
                for member in archive.getmembers()
                if member.isreg() and Path(member.name).name == basename
            ]
            if len(matches) != 1:
                return None
            source = archive.extractfile(matches[0])
            if source is None:
                return None
            with source:
                if gzip_compressed:
                    with gzip.GzipFile(fileobj=source, mode="rb") as decompressed:
                        return decompressed.read(byte_count)
                return source.read(byte_count)
    except (OSError, EOFError, tarfile.TarError):
        return None


def _validate_pgdump_header(archive_path: str) -> bool:
    """Extract and validate pg_dumpall header — must start with SQL comment."""
    header = _read_unique_archive_member_prefix(
        archive_path,
        "pgdumpall.sql.gz",
        100,
        gzip_compressed=True,
    )
    return bool(header and header.startswith(b"--"))


def _validate_redis_header(archive_path: str) -> bool:
    """Extract and validate Redis RDB header — must start with REDIS magic bytes."""
    with tarfile.open(archive_path, "r:gz") as archive:
        has_redis_dump = any(
            member.isreg() and Path(member.name).name == "redis-dump.rdb"
            for member in archive.getmembers()
        )
    if not has_redis_dump:
        # Redis dump may not exist (optional if Redis was unavailable)
        return True
    header = _read_unique_archive_member_prefix(
        archive_path,
        "redis-dump.rdb",
        5,
    )
    return bool(header and header.startswith(b"REDIS"))


def run_restore_tests() -> dict[str, Any]:
    """Run dry-run restore tests for all enabled backup sources.

    Returns:
        Summary with per-source results.
    """
    logger.info("run_restore_tests_started")

    sources = backup_store.list_sources()
    enabled_sources = [s for s in sources if s.get("enabled")]

    if not enabled_sources:
        return {"status": "success", "message": "No enabled sources", "tested": 0, "passed": 0, "failed": 0}

    results: list[dict[str, Any]] = []
    for source in enabled_sources:
        source_id = str(source["id"])
        try:
            result = run_restore_test_for_source(source_id)
            results.append(result)
        except Exception as e:
            logger.exception("restore_test_unhandled", source_id=source_id)
            results.append({"ok": False, "source_id": source_id, "error": str(e)})

    passed = sum(1 for r in results if r.get("ok"))
    failed = len(results) - passed

    logger.info("run_restore_tests_completed", tested=len(results), passed=passed, failed=failed)
    return {
        "status": "success" if failed == 0 else "partial",
        "tested": len(results),
        "passed": passed,
        "failed": failed,
        "results": results,
    }
