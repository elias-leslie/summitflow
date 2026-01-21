"""Browser console error monitor for detecting frontend errors.

Monitors explorer_entries for pages with console errors and creates
bug tasks for detected issues.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from ...logging_config import get_logger
from ...storage.tasks.core import create_task
from ...storage.tasks.dedup import bug_task_exists_for_error

logger = get_logger(__name__)


@dataclass
class BrowserError:
    """Represents a browser console error."""

    page_path: str
    page_id: int
    error_message: str
    error_count: int
    detected_at: str
    error_hash: str


def compute_console_error_hash(page_path: str, error_message: str) -> str:
    """Compute a stable hash for a console error for deduplication.

    Args:
        page_path: URL path of the page
        error_message: Console error message

    Returns:
        Hex digest of the error hash (16 characters)
    """
    # Normalize: lowercase, strip whitespace
    normalized = error_message.lower().strip()

    # Truncate long messages for stable hashing
    parts = [page_path, normalized[:200]]
    content = "|".join(parts)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def get_entries_with_console_errors(project_id: str) -> list[dict[str, Any]]:
    """Get page/endpoint entries that have console errors.

    Queries explorer_entries where health_data.console_error_count > 0.

    Args:
        project_id: Project ID to query

    Returns:
        List of entry dicts with console errors
    """
    from ...storage.connection import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, project_id, entry_type, path, name, health_status,
                   metadata, last_scanned_at, created_at, updated_at
            FROM explorer_entries
            WHERE project_id = %s
              AND entry_type IN ('page', 'endpoint')
              AND (metadata->'console_error_count')::int > 0
            ORDER BY (metadata->'console_error_count')::int DESC, path
            """,
            (project_id,),
        )
        rows = cur.fetchall()

    entries = []
    for row in rows:
        entry = {
            "id": row[0],
            "project_id": row[1],
            "entry_type": row[2],
            "path": row[3],
            "name": row[4],
            "health_status": row[5],
            "metadata": row[6] if row[6] else {},
            "last_scanned_at": row[7].isoformat() if row[7] else None,
            "created_at": row[8].isoformat() if row[8] else None,
            "updated_at": row[9].isoformat() if row[9] else None,
        }
        entries.append(entry)

    return entries


class BrowserErrorMonitor:
    """Monitor for browser console errors.

    Queries explorer_entries for pages with console errors and provides
    them for bug task creation.
    """

    def __init__(self, project_id: str):
        """Initialize the monitor.

        Args:
            project_id: Project ID to monitor
        """
        self.project_id = project_id
        self._seen_hashes: set[str] = set()

    def detect_errors(self) -> list[BrowserError]:
        """Detect browser console errors from explorer entries.

        Returns:
            List of BrowserError objects
        """
        entries = get_entries_with_console_errors(self.project_id)
        errors: list[BrowserError] = []

        for entry in entries:
            metadata = entry.get("metadata", {})
            console_errors = metadata.get("console_errors", [])
            error_count = metadata.get("console_error_count", 0)
            detected_at = entry.get("last_scanned_at") or entry.get("updated_at") or ""

            # Create BrowserError for each unique error message
            for error_msg in console_errors:
                if not error_msg or not isinstance(error_msg, str):
                    continue

                error_hash = compute_console_error_hash(entry["path"], error_msg)
                errors.append(
                    BrowserError(
                        page_path=entry["path"],
                        page_id=entry["id"],
                        error_message=error_msg,
                        error_count=error_count,
                        detected_at=detected_at,
                        error_hash=error_hash,
                    )
                )

        return errors

    def get_new_errors(self) -> list[BrowserError]:
        """Get new errors that haven't been seen before.

        Returns:
            List of new BrowserError objects
        """
        all_errors = self.detect_errors()
        new_errors = []

        for error in all_errors:
            if error.error_hash not in self._seen_hashes:
                new_errors.append(error)
                self._seen_hashes.add(error.error_hash)

        if new_errors:
            logger.info(
                "new_browser_errors_detected",
                count=len(new_errors),
                total_seen=len(all_errors),
                project_id=self.project_id,
            )

        return new_errors

    def mark_seen(self, error_hash: str) -> None:
        """Mark an error hash as seen."""
        self._seen_hashes.add(error_hash)


def create_browser_error_task(
    project_id: str,
    error: BrowserError,
    skip_dedup: bool = False,
) -> dict[str, Any] | None:
    """Create a bug task from a browser console error.

    Args:
        project_id: Project ID to create the task in
        error: BrowserError to create task from
        skip_dedup: If True, skip deduplication check

    Returns:
        Created task dict, or None if task already exists
    """
    # Build title from error message
    message_preview = error.error_message[:60]
    if len(error.error_message) > 60:
        message_preview += "..."
    title = f"Fix console error: {message_preview}"

    # Check for duplicate
    if not skip_dedup and bug_task_exists_for_error(project_id, title):
        logger.info(
            "skipping_duplicate_browser_error_task",
            error_hash=error.error_hash,
            title=title[:50],
        )
        return None

    # Build description with context
    description_parts = [
        f"**Detected:** {error.detected_at}",
        f"**Page:** {error.page_path}",
        f"**Error Count:** {error.error_count} total errors on this page",
        "",
        "**Console Error:**",
        "```",
        error.error_message,
        "```",
        "",
        f"**Error Hash:** {error.error_hash}",
        "",
        "This bug was auto-created from browser console error monitoring.",
        "The error was detected during page health checks.",
    ]
    description = "\n".join(description_parts)

    task = create_task(
        project_id=project_id,
        title=title,
        description=description,
        priority=2,  # P2 - standard priority
        task_type="bug",
        complexity="STANDARD",
        autonomous=True,  # Enable autonomous fixing
    )

    logger.info(
        "created_browser_error_task",
        task_id=task["id"],
        error_hash=error.error_hash,
        page_path=error.page_path,
    )

    return task


def process_browser_errors(
    project_id: str,
    monitor: BrowserErrorMonitor | None = None,
) -> dict[str, int]:
    """Process browser console errors and create bug tasks.

    Main entry point for the browser error monitoring workflow.

    Args:
        project_id: Project ID for task creation
        monitor: Optional BrowserErrorMonitor instance

    Returns:
        Dict with counts: created, skipped, errors
    """
    if monitor is None:
        monitor = BrowserErrorMonitor(project_id)

    results = {"created": 0, "skipped": 0, "errors": 0}

    try:
        new_errors = monitor.get_new_errors()

        for error in new_errors:
            try:
                task = create_browser_error_task(project_id, error)
                if task:
                    results["created"] += 1
                else:
                    results["skipped"] += 1
            except Exception as e:
                logger.error(
                    "browser_task_creation_failed",
                    error_hash=error.error_hash,
                    error=str(e),
                )
                results["errors"] += 1

    except Exception as e:
        logger.error("process_browser_errors_failed", error=str(e))
        results["errors"] += 1

    if results["created"] > 0:
        logger.info(
            "browser_error_processing_complete",
            project_id=project_id,
            **results,
        )

    return results


__all__ = [
    "BrowserError",
    "BrowserErrorMonitor",
    "compute_console_error_hash",
    "create_browser_error_task",
    "get_entries_with_console_errors",
    "process_browser_errors",
]
