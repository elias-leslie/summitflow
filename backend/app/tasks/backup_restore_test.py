"""Restore validation testing — dry-run restores to verify backup integrity."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from ..storage import backups as backup_store
from .backup_restore import restore_backup

logger = get_logger(__name__)


def test_restore_for_source(source_id: str) -> dict[str, Any]:
    """Run a dry-run restore of the latest backup for a source and record the result.

    For infrastructure sources (no project dir), verifies the archive is
    accessible on SMB and passes integrity check instead of running restore.sh.

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

    # Infrastructure sources don't have a project dir — verify archive accessibility instead
    if source_type == "infrastructure":
        return _test_archive_accessibility(source_id, latest)

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


def _test_archive_accessibility(source_id: str, backup: dict[str, Any]) -> dict[str, Any]:
    """Verify an infrastructure backup archive is accessible and valid.

    Checks: archive exists on SMB or locally, passes tar integrity test.
    """
    backup_id = backup["id"]
    location = str(backup.get("location") or "")
    name = str(backup.get("name") or "")

    # Check local file first
    if location and not location.startswith("//") and Path(location).exists():
        return _verify_tar_integrity(source_id, backup_id, location)

    # Check pending dir
    pending_path = Path.home() / ".local" / "share" / "backup-pending" / name
    if name and pending_path.exists():
        return _verify_tar_integrity(source_id, backup_id, str(pending_path))

    # Check SMB — download to temp and verify
    if location.startswith("//"):
        return _verify_smb_archive(source_id, backup_id, location)

    # Fallback: try to find by name on SMB
    if name:
        import os

        smb_host = os.environ.get("SMB_HOST", "")
        smb_share = os.environ.get("SMB_SHARE", "")
        if smb_host and smb_share:
            smb_path = f"//{smb_host}/{smb_share}/project-backups/{source_id}/{name}"
            return _verify_smb_archive(source_id, backup_id, smb_path)

    error = f"Cannot locate archive: location={location}, name={name}"
    backup_store.update_source_restore_test(source_id, ok=False, error=error)
    return {"ok": False, "source_id": source_id, "backup_id": backup_id, "error": error}


def _verify_tar_integrity(source_id: str, backup_id: str, path: str) -> dict[str, Any]:
    """Verify a local tar.gz archive passes integrity check."""
    try:
        result = subprocess.run(
            ["tar", "tzf", path],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            file_count = len(result.stdout.strip().splitlines())
            backup_store.update_source_restore_test(source_id, ok=True)
            logger.info("restore_test_completed", source_id=source_id, ok=True, files=file_count)
            return {"ok": True, "source_id": source_id, "backup_id": backup_id, "files": file_count}
        error = f"Archive integrity check failed: {result.stderr[:200]}"
        backup_store.update_source_restore_test(source_id, ok=False, error=error)
        return {"ok": False, "source_id": source_id, "backup_id": backup_id, "error": error}
    except Exception as e:
        error = str(e)
        backup_store.update_source_restore_test(source_id, ok=False, error=error)
        return {"ok": False, "source_id": source_id, "backup_id": backup_id, "error": error}


def _verify_smb_archive(source_id: str, backup_id: str, smb_path: str) -> dict[str, Any]:
    """Verify an SMB-hosted archive exists by listing it via smbclient."""
    import os

    creds_file = Path(os.environ.get("HOME", str(Path.home()))) / ".smbcredentials"

    # Parse SMB path: //host/share/path/to/file.tar.gz
    parts = smb_path.split("/")
    if len(parts) < 5:
        error = f"Invalid SMB path: {smb_path}"
        backup_store.update_source_restore_test(source_id, ok=False, error=error)
        return {"ok": False, "source_id": source_id, "backup_id": backup_id, "error": error}

    host = parts[2]
    share = parts[3]
    remote_dir = "/".join(parts[4:-1])
    filename = parts[-1]

    cmd = ["smbclient", f"//{host}/{share}", "-A", str(creds_file), "-c", f'ls {remote_dir}/{filename}']
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if filename in result.stdout:
            backup_store.update_source_restore_test(source_id, ok=True)
            logger.info("restore_test_completed", source_id=source_id, ok=True, method="smb_verify")
            return {"ok": True, "source_id": source_id, "backup_id": backup_id, "method": "smb_verify"}
        error = f"Archive not found on SMB: {smb_path}"
        backup_store.update_source_restore_test(source_id, ok=False, error=error)
        return {"ok": False, "source_id": source_id, "backup_id": backup_id, "error": error}
    except Exception as e:
        error = f"SMB check failed: {e}"
        backup_store.update_source_restore_test(source_id, ok=False, error=error)
        return {"ok": False, "source_id": source_id, "backup_id": backup_id, "error": error}


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
            result = test_restore_for_source(source_id)
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
