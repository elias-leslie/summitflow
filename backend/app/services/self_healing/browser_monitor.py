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

_ENTRY_COLS = (
    "id", "project_id", "entry_type", "path", "name",
    "health_status", "metadata", "last_scanned_at", "created_at", "updated_at",
)


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
    """Compute a stable 16-char SHA-256 hash for deduplication."""
    normalized = error_message.lower().strip()
    content = "|".join([page_path, normalized[:200]])
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _row_to_entry(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert a DB row tuple to an entry dict."""
    entry = dict(zip(_ENTRY_COLS, row, strict=True))
    entry["metadata"] = entry["metadata"] or {}
    for ts_key in ("last_scanned_at", "created_at", "updated_at"):
        val = entry[ts_key]
        entry[ts_key] = val.isoformat() if val else None
    return entry


_CONSOLE_ERROR_QUERY = """
    SELECT id, project_id, entry_type, path, name, health_status,
           metadata, last_scanned_at, created_at, updated_at
    FROM explorer_entries
    WHERE project_id = %s
      AND entry_type IN ('page', 'endpoint')
      AND (metadata->'console_error_count')::int > 0
    ORDER BY (metadata->'console_error_count')::int DESC, path
"""


def get_entries_with_console_errors(project_id: str) -> list[dict[str, Any]]:
    """Get page/endpoint entries that have console errors."""
    from ...storage.connection import get_cursor

    with get_cursor() as cur:
        cur.execute(_CONSOLE_ERROR_QUERY, (project_id,))
        rows = cur.fetchall()
    return [_row_to_entry(row) for row in rows]


def _errors_from_entry(entry: dict[str, Any]) -> list[BrowserError]:
    """Extract BrowserError objects from a single explorer entry."""
    metadata = entry.get("metadata", {})
    console_errors = metadata.get("console_errors", [])
    error_count = metadata.get("console_error_count", 0)
    detected_at = entry.get("last_scanned_at") or entry.get("updated_at") or ""
    errors: list[BrowserError] = []
    for error_msg in console_errors:
        if not error_msg or not isinstance(error_msg, str):
            continue
        errors.append(
            BrowserError(
                page_path=entry["path"],
                page_id=entry["id"],
                error_message=error_msg,
                error_count=error_count,
                detected_at=detected_at,
                error_hash=compute_console_error_hash(entry["path"], error_msg),
            )
        )
    return errors


class BrowserErrorMonitor:
    """Monitor for browser console errors from explorer_entries."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self._seen_hashes: set[str] = set()

    def detect_errors(self) -> list[BrowserError]:
        """Detect browser console errors from explorer entries."""
        entries = get_entries_with_console_errors(self.project_id)
        errors: list[BrowserError] = []
        for entry in entries:
            errors.extend(_errors_from_entry(entry))
        return errors

    def get_new_errors(self) -> list[BrowserError]:
        """Return errors not yet seen, updating the seen-hash set."""
        all_errors = self.detect_errors()
        new_errors = [e for e in all_errors if e.error_hash not in self._seen_hashes]
        self._seen_hashes.update(e.error_hash for e in new_errors)
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


def _build_error_description(error: BrowserError) -> str:
    """Build markdown description for a browser error task."""
    return "\n".join([
        f"**Detected:** {error.detected_at}",
        f"**Page:** {error.page_path}",
        f"**Error Count:** {error.error_count} total errors on this page",
        "", "**Console Error:**", "```", error.error_message, "```",
        "", f"**Error Hash:** {error.error_hash}", "",
        "This bug was auto-created from browser console error monitoring.",
        "The error was detected during page health checks.",
    ])


def create_browser_error_task(
    project_id: str,
    error: BrowserError,
    skip_dedup: bool = False,
) -> dict[str, Any] | None:
    """Create a bug task from a browser error; returns None if duplicate exists."""
    preview = error.error_message[:60] + ("..." if len(error.error_message) > 60 else "")
    title = f"Fix console error: {preview}"

    if not skip_dedup and bug_task_exists_for_error(project_id, title):
        logger.info("skipping_duplicate_browser_error_task", error_hash=error.error_hash, title=title[:50])
        return None

    task = create_task(
        project_id=project_id, title=title,
        description=_build_error_description(error),
        priority=2, task_type="bug", complexity="STANDARD", autonomous=True,
    )
    logger.info("created_browser_error_task", task_id=task["id"], error_hash=error.error_hash, page_path=error.page_path)
    return task


def process_browser_errors(
    project_id: str,
    monitor: BrowserErrorMonitor | None = None,
) -> dict[str, int]:
    """Process browser console errors, creating bug tasks. Returns created/skipped/errors counts."""
    if monitor is None:
        monitor = BrowserErrorMonitor(project_id)
    results: dict[str, int] = {"created": 0, "skipped": 0, "errors": 0}
    try:
        for error in monitor.get_new_errors():
            try:
                task = create_browser_error_task(project_id, error)
                results["created" if task else "skipped"] += 1
            except Exception as e:
                logger.error("browser_task_creation_failed", error_hash=error.error_hash, error=str(e))
                results["errors"] += 1
    except Exception as e:
        logger.error("process_browser_errors_failed", error=str(e))
        results["errors"] += 1
    if results["created"] > 0:
        logger.info("browser_error_processing_complete", project_id=project_id, **results)
    return results


__all__ = [
    "BrowserError",
    "BrowserErrorMonitor",
    "compute_console_error_hash",
    "create_browser_error_task",
    "get_entries_with_console_errors",
    "process_browser_errors",
]
