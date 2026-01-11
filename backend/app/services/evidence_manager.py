"""Evidence Manager - Service for managing UI verification evidence.

This module provides functions to:
- Save and retrieve evidence (screenshots + evidence.json)
- Track evidence versions
- Manage AI and user reviews
- Clean up old versions

Evidence is stored at: {project_data_dir}/evidence/{evidence_id}/v{n}/
Each version contains:
  - screenshot.png: Full page screenshot
  - evidence.json: Console, network, page state, performance data

Evidence is linked to:
- task_id: For task verification workflows
- explorer_entry_id: For explorer-driven captures (pages, components)
At least one is required.
"""

from __future__ import annotations

import asyncio
import json
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
    """Get evidence base directory for a project."""
    import os

    data_dir = os.environ.get("SUMMITFLOW_DATA_DIR", "/home/kasadis/summitflow/data")
    return Path(data_dir) / "projects" / project_id / "evidence"


def get_browser_scripts_dir() -> Path:
    """Get browser scripts directory."""
    import os

    claude_dir = os.environ.get("CLAUDE_CONFIG_DIR", "/home/kasadis/.claude")
    return Path(claude_dir) / "skills" / "browser-automation" / "scripts"


def get_evidence_path(
    project_id: str,
    evidence_id: str,
    version: int,
) -> Path:
    """Get the path for an evidence version.

    Uses flat structure: evidence/{evidence_id}/v{version}/
    """
    return get_evidence_base_dir(project_id) / evidence_id / f"v{version}"


async def capture_evidence(
    project_id: str,
    url: str,
    *,
    task_id: str | None = None,
    explorer_entry_id: int | None = None,
    evidence_type: str = "screenshot",
    criterion_db_id: int | None = None,
    test_run_id: int | None = None,
    auto_captured: bool = False,
    environment: str = "local",
    viewport_name: str | None = None,
) -> dict[str, Any]:
    """Capture evidence for a URL using the capture-evidence.js script.

    Args:
        project_id: Project ID for scoping
        url: The full URL to capture
        task_id: Task ID for linking (at least one of task_id/explorer_entry_id required)
        explorer_entry_id: Explorer entry ID for linking
        evidence_type: Type of evidence (screenshot, mockup, test-output, api-response, console_error)
        criterion_db_id: FK to acceptance_criteria.id (optional)
        test_run_id: FK to test_runs.id if captured during test run (optional)
        auto_captured: True if evidence was auto-captured on test pass
        environment: Environment (local, staging, production)
        viewport_name: Viewport name for multi-viewport captures

    Returns:
        Dict with success, version, file_path, evidence data
    """
    if not task_id and not explorer_entry_id:
        return {
            "success": False,
            "error": "At least one of task_id or explorer_entry_id is required",
        }

    scripts_dir = get_browser_scripts_dir()
    script_path = scripts_dir / "capture-evidence.js"
    evidence_base = get_evidence_base_dir(project_id)

    if not script_path.exists():
        return {
            "success": False,
            "error": f"Capture script not found: {script_path}",
        }

    evidence_base.mkdir(parents=True, exist_ok=True)

    # Generate evidence_id upfront so we can create the directory structure
    evidence_id = evidence_storage.generate_evidence_id()
    version = 1  # New evidence always starts at v1

    # Create the evidence directory
    evidence_dir = get_evidence_path(project_id, evidence_id, version)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    try:
        proc = await asyncio.create_subprocess_exec(
            "node",
            str(script_path),
            url,
            str(evidence_dir),
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

            if parsed.get("success"):
                file_path = str(evidence_dir.relative_to(evidence_base))
                file_size = parsed.get("file_size_bytes")

                # Save to database
                with get_connection() as conn, conn.cursor() as cur:
                    # Mark previous versions as stale
                    evidence_storage.mark_previous_as_stale(
                        cur,
                        project_id,
                        task_id=task_id,
                        explorer_entry_id=explorer_entry_id,
                        evidence_type=evidence_type,
                    )

                    # Insert new record
                    rec_id, rec_evidence_id, captured_ts = evidence_storage.insert_evidence_record(
                        cur,
                        project_id,
                        file_path,
                        file_size,
                        task_id=task_id,
                        explorer_entry_id=explorer_entry_id,
                        evidence_type=evidence_type,
                        version=version,
                        criterion_db_id=criterion_db_id,
                        test_run_id=test_run_id,
                        auto_captured=auto_captured,
                        environment=environment,
                        viewport_name=viewport_name,
                    )
                    conn.commit()

                parsed["evidence_id"] = rec_evidence_id
                parsed["db_id"] = rec_id
                parsed["file_path"] = file_path
                parsed["version"] = version

                logger.info(
                    "evidence_captured",
                    project_id=project_id,
                    evidence_id=rec_evidence_id,
                    task_id=task_id,
                    explorer_entry_id=explorer_entry_id,
                    version=version,
                )

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


async def capture_console_errors(
    project_id: str,
    url: str,
    *,
    task_id: str | None = None,
    explorer_entry_id: int | None = None,
    console_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Capture console errors as separate evidence.

    Args:
        project_id: Project ID for scoping
        url: The URL where errors were captured
        task_id: Task ID for linking
        explorer_entry_id: Explorer entry ID for linking
        console_data: Pre-captured console data (errors, warnings)

    Returns:
        Dict with success, evidence_id
    """
    if not task_id and not explorer_entry_id:
        return {
            "success": False,
            "error": "At least one of task_id or explorer_entry_id is required",
        }

    if not console_data or not console_data.get("errors"):
        return {
            "success": False,
            "error": "No console errors to capture",
        }

    evidence_base = get_evidence_base_dir(project_id)
    evidence_id = evidence_storage.generate_evidence_id()
    version = 1

    evidence_dir = get_evidence_path(project_id, evidence_id, version)
    evidence_dir.mkdir(parents=True, exist_ok=True)

    # Save console data as JSON
    console_file = evidence_dir / "console_errors.json"
    console_file.write_text(
        json.dumps(
            {
                "url": url,
                "captured_at": datetime.now().isoformat(),
                "errors": console_data.get("errors", []),
                "warnings": console_data.get("warnings", []),
                "error_count": len(console_data.get("errors", [])),
                "warning_count": len(console_data.get("warnings", [])),
            },
            indent=2,
        )
    )

    file_path = str(evidence_dir.relative_to(evidence_base))
    file_size = console_file.stat().st_size

    with get_connection() as conn, conn.cursor() as cur:
        rec_id, rec_evidence_id, _ = evidence_storage.insert_evidence_record(
            cur,
            project_id,
            file_path,
            file_size,
            task_id=task_id,
            explorer_entry_id=explorer_entry_id,
            evidence_type="console_error",
            version=version,
        )
        conn.commit()

    logger.info(
        "console_errors_captured",
        project_id=project_id,
        evidence_id=rec_evidence_id,
        error_count=len(console_data.get("errors", [])),
    )

    return {
        "success": True,
        "evidence_id": rec_evidence_id,
        "db_id": rec_id,
        "file_path": file_path,
        "error_count": len(console_data.get("errors", [])),
    }


def save_evidence(
    project_id: str,
    file_path: str,
    *,
    task_id: str | None = None,
    explorer_entry_id: int | None = None,
    evidence_type: str = "screenshot",
    file_size_bytes: int | None = None,
    criterion_db_id: int | None = None,
    test_run_id: int | None = None,
    auto_captured: bool = False,
    linked_evidence_id: int | None = None,
    mockup_status: str | None = None,
    environment: str = "local",
    viewport_name: str | None = None,
) -> dict[str, Any]:
    """Save an evidence record to the database.

    Args:
        project_id: Project ID for scoping
        file_path: Relative path to evidence directory
        task_id: Task ID for linking (at least one required)
        explorer_entry_id: Explorer entry ID for linking
        evidence_type: Type of evidence
        file_size_bytes: Total size of files
        criterion_db_id: FK to acceptance_criteria.id (optional)
        test_run_id: FK to test_runs.id if captured during test run (optional)
        auto_captured: True if evidence was auto-captured on test pass
        linked_evidence_id: FK to evidence.id for mockup comparison
        mockup_status: Status for mockup evidence
        environment: Environment (local, staging, production)
        viewport_name: Viewport name for multi-viewport captures

    Returns:
        Created evidence record
    """
    version = evidence_storage.get_next_version(
        project_id,
        task_id=task_id,
        explorer_entry_id=explorer_entry_id,
        evidence_type=evidence_type,
    )

    with get_connection() as conn, conn.cursor() as cur:
        evidence_storage.mark_previous_as_stale(
            cur,
            project_id,
            task_id=task_id,
            explorer_entry_id=explorer_entry_id,
            evidence_type=evidence_type,
        )
        rec_id, rec_evidence_id, captured_ts = evidence_storage.insert_evidence_record(
            cur,
            project_id,
            file_path,
            file_size_bytes,
            task_id=task_id,
            explorer_entry_id=explorer_entry_id,
            evidence_type=evidence_type,
            version=version,
            criterion_db_id=criterion_db_id,
            test_run_id=test_run_id,
            auto_captured=auto_captured,
            linked_evidence_id=linked_evidence_id,
            mockup_status=mockup_status,
            environment=environment,
            viewport_name=viewport_name,
        )
        conn.commit()

        logger.info(
            "evidence_saved",
            project_id=project_id,
            evidence_id=rec_evidence_id,
            task_id=task_id,
            explorer_entry_id=explorer_entry_id,
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


# Re-export storage functions
get_evidence_by_id = evidence_storage.get_evidence_by_id
get_evidence_for_task = evidence_storage.get_evidence_for_task
get_evidence_for_entry = evidence_storage.get_evidence_for_entry
get_latest_evidence = evidence_storage.get_latest_evidence
get_next_version = evidence_storage.get_next_version
list_evidence = evidence_storage.list_evidence
get_pending_review = evidence_storage.get_pending_review
get_needs_user_review = evidence_storage.get_needs_user_review
get_with_user_notes = evidence_storage.get_with_user_notes
get_auto_captured_evidence = evidence_storage.get_auto_captured_evidence
get_summary = evidence_storage.get_summary
get_mockups_for_entry = evidence_storage.get_mockups_for_entry
get_approved_mockup = evidence_storage.get_approved_mockup
update_mockup_status = evidence_storage.update_mockup_status
EVIDENCE_TYPES = evidence_storage.EVIDENCE_TYPES
MOCKUP_STATUSES = evidence_storage.MOCKUP_STATUSES
generate_evidence_id = evidence_storage.generate_evidence_id


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


def read_evidence_file(
    project_id: str,
    evidence_id: str,
    version: int | None = None,
) -> dict[str, Any] | None:
    """Read the evidence.json file for evidence.

    Args:
        project_id: Project ID for scoping
        evidence_id: Evidence ID (ev-{uuid})
        version: Optional version (defaults to 1)

    Returns:
        Parsed evidence.json data or None
    """
    if version is None:
        version = 1

    evidence_dir = get_evidence_path(project_id, evidence_id, version)
    evidence_path = evidence_dir / "evidence.json"

    if not evidence_path.exists():
        return None

    try:
        with evidence_path.open() as f:
            data: dict[str, Any] = json.load(f)
            return data
    except Exception as e:
        logger.error("read_evidence_failed", path=str(evidence_path), error=str(e))
        return None
