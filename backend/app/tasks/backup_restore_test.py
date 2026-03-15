"""Restore validation testing — dry-run restores to verify backup integrity."""

from __future__ import annotations

from typing import Any

from ..logging_config import get_logger
from ..storage import backups as backup_store
from .backup_restore import restore_backup

logger = get_logger(__name__)


def test_restore_for_source(source_id: str) -> dict[str, Any]:
    """Run a dry-run restore of the latest backup for a source and record the result.

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

    project_id = str(source.get("project_id") or source_id)
    backup_id = latest["id"]

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
