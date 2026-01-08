"""Evidence Manager - Service for managing UI verification evidence.

This module provides functions to:
- Save and retrieve evidence (screenshots + evidence.json)
- Track evidence versions
- Manage AI and user reviews
- Clean up old versions

Evidence is stored at: {project_data_dir}/evidence/{capability_id}/{criterion_id}/v{n}/
Each version contains:
  - screenshot.png: Full page screenshot
  - evidence.json: Console, network, page state, performance data

Extracted from portfolio-ai/backend/app/services/artifact_manager.py
Changes from source:
  - Renamed "artifacts" -> "evidence" throughout
  - Added project_id parameter to all functions
  - Uses get_connection() context manager
  - Evidence paths are project-relative
  - Database operations moved to storage/evidence.py
"""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from ..storage import evidence as evidence_storage
from ..storage.connection import get_connection

logger = get_logger(__name__)

# Configuration defaults (can be overridden per-project)
MAX_VERSIONS_TO_KEEP = 5
CAPTURE_TIMEOUT_SECONDS = 60


def get_evidence_base_dir(project_id: str) -> Path:
    """Get evidence base directory for a project.

    TODO: Fetch from project config in database.
    For now, use a standard path structure.
    """
    import os

    data_dir = os.environ.get("SUMMITFLOW_DATA_DIR", "/home/kasadis/summitflow/data")
    return Path(data_dir) / "projects" / project_id / "evidence"


def get_browser_scripts_dir(project_id: str) -> Path:
    """Get browser scripts directory.

    These are part of the SummitFlow/Claude installation, shared across projects.
    """
    import os

    claude_dir = os.environ.get("CLAUDE_CONFIG_DIR", "/home/kasadis/.claude")
    return Path(claude_dir) / "skills" / "browser-automation" / "scripts"


def generate_evidence_id(capability_id: str, criterion_id: str, version: int) -> str:
    """Generate a unique evidence ID."""
    return f"{capability_id}-{criterion_id}-v{version}"


async def capture_evidence(
    project_id: str,
    url: str,
    capability_id: str,
    criterion_id: str,
    criterion_db_id: int | None = None,
    test_run_id: int | None = None,
    auto_captured: bool = False,
) -> dict[str, Any]:
    """Capture evidence for a UI criterion using the capture-evidence.js script.

    Args:
        project_id: Project ID for scoping
        url: The full URL to capture
        capability_id: Capability ID (e.g., login, password-reset)
        criterion_id: Criterion ID (e.g., ac-001)
        criterion_db_id: FK to acceptance_criteria.id (optional)
        test_run_id: FK to test_runs.id if captured during test run (optional)
        auto_captured: True if evidence was auto-captured on test pass

    Returns:
        Dict with success, version, file_path, evidence data
    """
    scripts_dir = get_browser_scripts_dir(project_id)
    script_path = scripts_dir / "capture-evidence.js"
    evidence_base = get_evidence_base_dir(project_id)

    if not script_path.exists():
        return {
            "success": False,
            "error": f"Capture script not found: {script_path}",
        }

    evidence_base.mkdir(parents=True, exist_ok=True)

    try:
        proc = await asyncio.create_subprocess_exec(
            "node",
            str(script_path),
            url,
            capability_id,
            criterion_id,
            str(evidence_base),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, _stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=CAPTURE_TIMEOUT_SECONDS,
        )

        output = stdout.decode()

        result_line = None
        for line in output.split("\n"):
            if line.startswith("{") and '"success"' in line:
                result_line = line
                break

        if result_line:
            parsed: dict[str, Any] = json.loads(result_line)

            # If capture was successful and we have FK links, save to database
            if parsed.get("success") and (criterion_db_id or test_run_id or auto_captured):
                version = parsed.get("version", 1)
                file_path = parsed.get("file_path", "")

                # Save with new FK columns
                save_result = save_evidence(
                    project_id=project_id,
                    capability_id=capability_id,
                    criterion_id=criterion_id,
                    version=version,
                    file_path=file_path,
                    file_size_bytes=parsed.get("file_size_bytes"),
                    criterion_db_id=criterion_db_id,
                    test_run_id=test_run_id,
                    auto_captured=auto_captured,
                )
                parsed["evidence_id"] = save_result.get("evidence_id")
                parsed["db_id"] = save_result.get("id")

            return parsed

        return {
            "success": False,
            "error": f"Could not parse script output: {output[:500]}",
        }

    except TimeoutError:
        return {
            "success": False,
            "error": f"Capture timed out after {CAPTURE_TIMEOUT_SECONDS}s",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def save_evidence(
    project_id: str,
    capability_id: str,
    criterion_id: str,
    version: int,
    file_path: str,
    file_size_bytes: int | None = None,
    evidence_data: dict[str, Any] | None = None,
    criterion_db_id: int | None = None,
    test_run_id: int | None = None,
    auto_captured: bool = False,
) -> dict[str, Any]:
    """Save an evidence record to the database.

    Args:
        project_id: Project ID for scoping
        capability_id: Feature ID (e.g., FEAT-001)
        criterion_id: Criterion ID (e.g., ac-001)
        version: Version number
        file_path: Relative path to evidence directory
        file_size_bytes: Total size of files
        evidence_data: Parsed evidence.json data
        criterion_db_id: FK to acceptance_criteria.id (optional)
        test_run_id: FK to test_runs.id if captured during test run (optional)
        auto_captured: True if evidence was auto-captured on test pass

    Returns:
        Created evidence record
    """
    evidence_id = generate_evidence_id(capability_id, criterion_id, version)

    with get_connection() as conn, conn.cursor() as cur:
        evidence_storage.mark_previous_as_stale(cur, project_id, capability_id, criterion_id)
        rec_id, rec_evidence_id, captured_ts = evidence_storage.insert_evidence_record(
            cur,
            project_id,
            evidence_id,
            capability_id,
            criterion_id,
            file_path,
            file_size_bytes,
            version,
            criterion_db_id,
            test_run_id,
            auto_captured,
        )
        conn.commit()

        logger.info(
            "evidence_saved",
            project_id=project_id,
            evidence_id=evidence_id,
            capability_id=capability_id,
            criterion_id=criterion_id,
            version=version,
        )

        captured_iso: str | None = None
        if captured_ts is not None and isinstance(captured_ts, datetime):
            captured_iso = captured_ts.isoformat()

        return {
            "id": rec_id,
            "evidence_id": rec_evidence_id,
            "captured_at": captured_iso,
            "version": version,
            "file_path": file_path,
        }


# Re-export storage functions for backwards compatibility
get_evidence = evidence_storage.get_evidence
get_latest_evidence = evidence_storage.get_latest_evidence
get_next_version = evidence_storage.get_next_version
get_evidence_versions = evidence_storage.get_evidence_versions
list_evidence = evidence_storage.list_evidence
get_pending_review = evidence_storage.get_pending_review
get_needs_user_review = evidence_storage.get_needs_user_review
get_with_user_notes = evidence_storage.get_with_user_notes
get_auto_captured_evidence = evidence_storage.get_auto_captured_evidence
get_summary = evidence_storage.get_summary
get_test_evidence = evidence_storage.get_test_evidence


def update_ai_review(
    project_id: str,
    evidence_id: str,
    quality_status: str,
    confidence: float,
    ai_evidence: str | None = None,
    quality_issues: list[str] | None = None,
    reviewed_by: str = "claude",
) -> bool:
    """Record AI review result for evidence."""
    result = evidence_storage.update_ai_review(
        project_id=project_id,
        evidence_id=evidence_id,
        quality_status=quality_status,
        confidence=confidence,
        ai_evidence=ai_evidence,
        quality_issues=quality_issues,
        reviewed_by=reviewed_by,
    )
    if result:
        logger.info(
            "ai_review_recorded",
            project_id=project_id,
            evidence_id=evidence_id,
            quality_status=quality_status,
            confidence=confidence,
        )
    return result


def update_user_review(
    project_id: str,
    evidence_id: str,
    approved: bool | None,
    notes: str | None = None,
) -> bool:
    """Record user review for evidence."""
    result = evidence_storage.update_user_review(
        project_id=project_id,
        evidence_id=evidence_id,
        approved=approved,
        notes=notes,
    )
    if result:
        logger.info(
            "user_review_recorded",
            project_id=project_id,
            evidence_id=evidence_id,
            approved=approved,
        )
    return result


def cleanup_old_versions(
    project_id: str,
    capability_id: str | None = None,
    max_versions: int = MAX_VERSIONS_TO_KEEP,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Delete old evidence versions beyond retention limit.

    Args:
        project_id: Project ID for scoping
        capability_id: Optional filter by feature
        max_versions: Max versions to keep per criterion
        dry_run: If True, only report what would be deleted

    Returns:
        Summary of cleanup operation
    """
    evidence_base = get_evidence_base_dir(project_id)
    deleted_count = 0
    deleted_size = 0

    with get_connection() as conn, conn.cursor() as cur:
        pairs = evidence_storage.get_evidence_pairs_to_clean(cur, project_id, capability_id)

        for feat_id, crit_id in pairs:
            count, size = evidence_storage.delete_old_versions_for_pair(
                cur, project_id, feat_id, crit_id, max_versions, evidence_base, dry_run
            )
            deleted_count += count
            deleted_size += size

        if not dry_run:
            conn.commit()

    logger.info(
        "cleanup_old_versions",
        project_id=project_id,
        deleted_count=deleted_count,
        deleted_size_bytes=deleted_size,
        dry_run=dry_run,
    )

    return {
        "deleted_count": deleted_count,
        "deleted_size_bytes": deleted_size,
        "dry_run": dry_run,
    }


def read_evidence_file(
    project_id: str,
    capability_id: str,
    criterion_id: str,
    version: int | None = None,
) -> dict[str, Any] | None:
    """Read the evidence.json file for evidence.

    Args:
        project_id: Project ID for scoping
        capability_id: Feature ID
        criterion_id: Criterion ID
        version: Optional version (defaults to current)

    Returns:
        Parsed evidence.json data or None
    """
    evidence_base = get_evidence_base_dir(project_id)

    if version:
        evidence_path = (
            evidence_base / capability_id / criterion_id / f"v{version}" / "evidence.json"
        )
    else:
        evidence_path = evidence_base / capability_id / criterion_id / "current" / "evidence.json"

    if not evidence_path.exists():
        return None

    try:
        with evidence_path.open() as f:
            data: dict[str, Any] = json.load(f)
            return data
    except Exception as e:
        logger.error("read_evidence_failed", path=str(evidence_path), error=str(e))
        return None


# ============================================================
# Test Evidence Integration
# ============================================================


def register_test_evidence(
    project_id: str,
    test_id: str,
    test_run_id: int,
    evidence_path: str,
    capability_id: str | None = None,
) -> dict[str, Any] | None:
    """Register evidence from a UI test run.

    Creates an evidence record linked to a test run. Uses test_id as capability_id
    and "test-run" as criterion_id for test-generated evidence.

    Args:
        project_id: Project ID for scoping
        test_id: The test ID (used as capability_id for evidence)
        test_run_id: The test_runs table ID for linking
        evidence_path: Path to the evidence file (screenshot, etc.)
        capability_id: Optional capability ID if test is linked to one

    Returns:
        Created evidence record or None if path doesn't exist
    """
    evidence_file = Path(evidence_path)
    if not evidence_file.exists():
        logger.warning(
            "test_evidence_not_found",
            project_id=project_id,
            test_id=test_id,
            path=evidence_path,
        )
        return None

    # Use test_id as capability_id and "test-run-{id}" as criterion for uniqueness
    test_capability_id = f"test-{test_id}"
    criterion_id = f"run-{test_run_id}"

    # Get next version
    version = evidence_storage.get_next_version(project_id, test_capability_id, criterion_id)

    # Get file size
    file_size = evidence_file.stat().st_size if evidence_file.exists() else 0

    # Copy evidence to standard location
    evidence_base = get_evidence_base_dir(project_id)
    dest_dir = evidence_base / test_capability_id / criterion_id / f"v{version}"
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_path = dest_dir / evidence_file.name
    shutil.copy2(evidence_file, dest_path)

    # Save evidence record with test_run_id link
    result = save_evidence(
        project_id=project_id,
        capability_id=test_capability_id,
        criterion_id=criterion_id,
        version=version,
        file_path=str(dest_dir.relative_to(evidence_base)),
        file_size_bytes=file_size,
        test_run_id=test_run_id,
    )

    # Update test_runs with evidence_path
    evidence_storage.update_test_run_evidence_path(test_run_id, str(dest_path))

    logger.info(
        "test_evidence_registered",
        project_id=project_id,
        test_id=test_id,
        test_run_id=test_run_id,
        evidence_id=result.get("evidence_id"),
        version=version,
    )

    return result
