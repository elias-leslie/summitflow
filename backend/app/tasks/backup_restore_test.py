"""Restore validation testing — dry-run restores to verify backup integrity."""

from __future__ import annotations

import gzip
import subprocess
import tarfile
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from ..storage import backups as backup_store
from .backup_coverage import verify_archive_coverage
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

    archive_path = _locate_archive(location, name, source_id)
    if archive_path is None:
        error = f"Cannot locate archive: location={location}, name={name}"
        backup_store.update_source_restore_test(source_id, ok=False, error=error)
        return {"ok": False, "source_id": source_id, "backup_id": backup_id, "error": error}

    # 1. Tar integrity
    try:
        result = subprocess.run(
            ["tar", "tzf", archive_path],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            error = f"Archive integrity check failed: {result.stderr[:200]}"
            backup_store.update_source_restore_test(source_id, ok=False, error=error)
            _cleanup_temp_archive(archive_path, location)
            return {"ok": False, "source_id": source_id, "backup_id": backup_id, "error": error}
        file_listing = result.stdout.strip().splitlines()
    except Exception as e:
        error = str(e)
        backup_store.update_source_restore_test(source_id, ok=False, error=error)
        _cleanup_temp_archive(archive_path, location)
        return {"ok": False, "source_id": source_id, "backup_id": backup_id, "error": error}

    # 2. Coverage contract check
    coverage_result = verify_archive_coverage(verification_json)
    coverage_ok = coverage_result.complete

    # 3. Validate pg_dumpall header (quick sanity check)
    pg_ok = _validate_pgdump_header(archive_path)

    # 4. Validate Redis RDB header
    redis_ok = _validate_redis_header(archive_path)

    # Aggregate result
    errors: list[str] = []
    if not coverage_ok:
        errors.append(f"Missing required components: {', '.join(coverage_result.missing)}")
    if not pg_ok:
        errors.append("PostgreSQL dump header validation failed")
    if not redis_ok and _has_file_in_listing(file_listing, "redis-dump.rdb"):
        errors.append("Redis RDB header validation failed")

    all_ok = coverage_ok and pg_ok
    backup_store.update_source_restore_test(source_id, ok=all_ok, error="; ".join(errors) if errors else None)
    _cleanup_temp_archive(archive_path, location)

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


def _locate_archive(location: str, name: str, source_id: str) -> str | None:
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
        return _download_smb_archive(smb_path)

    return None


def _download_smb_archive(smb_path: str) -> str | None:
    """Download an archive from SMB to a temp file. Returns local path or None."""
    import os
    import tempfile

    creds_file = Path(os.environ.get("HOME", str(Path.home()))) / ".smbcredentials"
    parts = smb_path.split("/")
    if len(parts) < 5:
        return None

    host, share = parts[2], parts[3]
    remote_dir = "/".join(parts[4:-1])
    filename = parts[-1]

    temp_path = Path(tempfile.mkdtemp()) / filename
    cmd = [
        "smbclient", f"//{host}/{share}", "-A", str(creds_file),
        "-c", f"cd {remote_dir}; get {filename} {temp_path}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0 and temp_path.exists():
            return str(temp_path)
    except Exception:
        pass
    return None


def _cleanup_temp_archive(archive_path: str, original_location: str) -> None:
    """Remove temp archive if it was downloaded from SMB."""
    if original_location.startswith("//") and Path(archive_path).exists():
        import shutil
        parent = Path(archive_path).parent
        if str(parent).startswith("/tmp/"):
            shutil.rmtree(parent, ignore_errors=True)


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
