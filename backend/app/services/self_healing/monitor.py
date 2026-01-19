"""Systemd journal monitor for detecting runtime errors.

Monitors systemd journal for errors from SummitFlow services and creates
bug tasks for detected issues.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ...logging_config import get_logger
from ...storage.tasks.core import create_task
from ...storage.tasks.dedup import bug_task_exists_for_error

logger = get_logger(__name__)

# Journal priority levels (lower = more severe)
PRIORITY_EMERG = 0
PRIORITY_ALERT = 1
PRIORITY_CRIT = 2
PRIORITY_ERR = 3
PRIORITY_WARNING = 4
PRIORITY_NOTICE = 5
PRIORITY_INFO = 6
PRIORITY_DEBUG = 7

# Capture errors and above (priority <= 3)
ERROR_PRIORITY_THRESHOLD = PRIORITY_ERR


@dataclass
class JournalError:
    """Represents an error extracted from systemd journal."""

    unit: str
    message: str
    priority: int
    timestamp: datetime
    error_hash: str


def compute_error_hash(unit: str, message: str) -> str:
    """Compute a stable hash for an error for deduplication.

    The hash is based on the unit and a normalized version of the message,
    ignoring timestamps and specific values that vary.

    Args:
        unit: Systemd unit name
        message: Error message

    Returns:
        Hex digest of the error hash (16 characters)
    """
    # Normalize: lowercase, strip whitespace
    normalized = message.lower().strip()

    # Remove common varying parts (line numbers, PIDs, timestamps)
    # This is a simple approach; can be refined based on actual patterns
    parts = [unit, normalized[:200]]  # Truncate long messages
    content = "|".join(parts)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


class SystemdMonitor:
    """Monitor for systemd journal errors.

    Parses journalctl output to detect errors from SummitFlow services
    and provides them for bug task creation.
    """

    def __init__(
        self,
        unit_pattern: str = "summitflow-*",
        since: str = "5 minutes ago",
    ):
        """Initialize the monitor.

        Args:
            unit_pattern: Pattern for matching systemd units
            since: Time window for journal queries
        """
        self.unit_pattern = unit_pattern
        self.since = since
        self._seen_hashes: set[str] = set()

    def parse_journal(self) -> list[JournalError]:
        """Parse journalctl output for errors.

        Runs journalctl and extracts error-level entries.

        Returns:
            List of JournalError objects
        """
        try:
            result = subprocess.run(
                [
                    "journalctl",
                    "--user",
                    "-u",
                    self.unit_pattern,
                    "--since",
                    self.since,
                    "-o",
                    "json",
                    "--no-pager",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                logger.warning(
                    "journalctl_failed",
                    returncode=result.returncode,
                    stderr=result.stderr[:200],
                )
                return []

            return self._parse_json_output(result.stdout)

        except subprocess.TimeoutExpired:
            logger.warning("journalctl_timeout")
            return []
        except FileNotFoundError:
            logger.warning("journalctl_not_found")
            return []
        except Exception as e:
            logger.error("journal_parse_error", error=str(e))
            return []

    def _parse_json_output(self, output: str) -> list[JournalError]:
        """Parse JSON output from journalctl.

        Each line is a separate JSON object.

        Args:
            output: Raw journalctl output

        Returns:
            List of parsed errors
        """
        errors: list[JournalError] = []

        for line in output.strip().split("\n"):
            if not line:
                continue

            try:
                entry = json.loads(line)
                error = self._parse_entry(entry)
                if error:
                    errors.append(error)
            except json.JSONDecodeError:
                logger.debug("skipping_non_json_line", line=line[:50])
                continue

        return errors

    def _parse_entry(self, entry: dict[str, str]) -> JournalError | None:
        """Parse a single journal entry.

        Args:
            entry: JSON-decoded journal entry

        Returns:
            JournalError if entry is an error, None otherwise
        """
        # Get priority (defaults to INFO if not present)
        priority_str = entry.get("PRIORITY", str(PRIORITY_INFO))
        try:
            priority = int(priority_str)
        except ValueError:
            priority = PRIORITY_INFO

        # Only capture errors and above
        if priority > ERROR_PRIORITY_THRESHOLD:
            return None

        # Extract required fields
        unit = entry.get("_SYSTEMD_UNIT", entry.get("UNIT", "unknown"))
        message = entry.get("MESSAGE", "")

        if not message:
            return None

        # Parse timestamp
        timestamp_us = entry.get("__REALTIME_TIMESTAMP")
        if timestamp_us:
            try:
                timestamp = datetime.fromtimestamp(int(timestamp_us) / 1_000_000)
            except (ValueError, OSError):
                timestamp = datetime.now()
        else:
            timestamp = datetime.now()

        error_hash = compute_error_hash(unit, message)

        return JournalError(
            unit=unit,
            message=message,
            priority=priority,
            timestamp=timestamp,
            error_hash=error_hash,
        )

    def get_new_errors(self) -> list[JournalError]:
        """Get new errors that haven't been seen before.

        Filters out errors that have already been processed based on
        their error hash.

        Returns:
            List of new JournalError objects
        """
        all_errors = self.parse_journal()
        new_errors = []

        for error in all_errors:
            if error.error_hash not in self._seen_hashes:
                new_errors.append(error)
                self._seen_hashes.add(error.error_hash)

        if new_errors:
            logger.info(
                "new_errors_detected",
                count=len(new_errors),
                total_seen=len(all_errors),
            )

        return new_errors

    def mark_seen(self, error_hash: str) -> None:
        """Mark an error hash as seen.

        Used when loading known errors from database.

        Args:
            error_hash: Hash to mark as seen
        """
        self._seen_hashes.add(error_hash)

    def clear_seen(self) -> None:
        """Clear the set of seen error hashes.

        Use with caution - may cause duplicate task creation.
        """
        self._seen_hashes.clear()


def _get_priority_name(priority: int) -> str:
    """Get human-readable name for priority level."""
    names = {
        PRIORITY_EMERG: "EMERGENCY",
        PRIORITY_ALERT: "ALERT",
        PRIORITY_CRIT: "CRITICAL",
        PRIORITY_ERR: "ERROR",
    }
    return names.get(priority, "ERROR")


def create_error_task(
    project_id: str,
    error: JournalError,
    skip_dedup: bool = False,
) -> dict[str, Any] | None:
    """Create a bug task from a journal error.

    Args:
        project_id: Project ID to create the task in
        error: JournalError to create task from
        skip_dedup: If True, skip deduplication check

    Returns:
        Created task dict, or None if task already exists
    """
    # Build title from error message
    # Truncate at 80 chars for readability
    message_preview = error.message[:80]
    if len(error.message) > 80:
        message_preview += "..."
    title = f"Fix: {message_preview}"

    # Check for duplicate
    if not skip_dedup and bug_task_exists_for_error(project_id, title):
        logger.info(
            "skipping_duplicate_error_task",
            error_hash=error.error_hash,
            title=title[:50],
        )
        return None

    # Build description with full context
    priority_name = _get_priority_name(error.priority)
    description_parts = [
        f"**Detected:** {error.timestamp.isoformat()}",
        f"**Service:** {error.unit}",
        f"**Priority:** {priority_name}",
        "",
        "**Error Message:**",
        "```",
        error.message,
        "```",
        "",
        f"**Error Hash:** {error.error_hash}",
        "",
        "This bug was auto-created from systemd journal monitoring.",
        "The error was detected at runtime and requires investigation.",
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
        "created_error_task",
        task_id=task["id"],
        error_hash=error.error_hash,
        unit=error.unit,
    )

    return task


def process_journal_errors(
    project_id: str,
    monitor: SystemdMonitor | None = None,
) -> dict[str, int]:
    """Process journal errors and create bug tasks.

    Main entry point for the monitoring workflow.

    Args:
        project_id: Project ID for task creation
        monitor: Optional SystemdMonitor instance

    Returns:
        Dict with counts: created, skipped, errors
    """
    if monitor is None:
        monitor = SystemdMonitor()

    results = {"created": 0, "skipped": 0, "errors": 0}

    try:
        new_errors = monitor.get_new_errors()

        for error in new_errors:
            try:
                task = create_error_task(project_id, error)
                if task:
                    results["created"] += 1
                else:
                    results["skipped"] += 1
            except Exception as e:
                logger.error(
                    "task_creation_failed",
                    error_hash=error.error_hash,
                    error=str(e),
                )
                results["errors"] += 1

    except Exception as e:
        logger.error("process_journal_errors_failed", error=str(e))
        results["errors"] += 1

    if results["created"] > 0:
        logger.info(
            "journal_processing_complete",
            **results,
        )

    return results
