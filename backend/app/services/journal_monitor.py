"""Systemd journal reader for runtime error findings (used by runtime hygiene)."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime

from ..logging_config import get_logger
from ..utils import safe_subprocess

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
ERROR_PRIORITY_THRESHOLD = PRIORITY_ERR  # Capture errors and above (priority <= 3)

_JOURNAL_TIMEOUT = 30
_HASH_TRUNCATE_LEN = 200
_HASH_DIGEST_LEN = 16


@dataclass
class JournalError:
    """Represents an error extracted from systemd journal."""
    unit: str
    message: str
    priority: int
    timestamp: datetime
    error_hash: str


def compute_error_hash(unit: str, message: str) -> str:
    """Compute a stable 16-char deduplication hash, stripping timestamps/numbers."""
    norm = re.sub(r"\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}[.,]?\d*[Zz]?", "", message.lower().strip())
    norm = re.sub(r"\s+", " ", re.sub(r"\b\d{2,}\b", "", norm)).strip()
    return hashlib.sha256(f"{unit}|{norm[:_HASH_TRUNCATE_LEN]}".encode()).hexdigest()[:_HASH_DIGEST_LEN]


class SystemdMonitor:
    """Monitor systemd journal for errors from SummitFlow services."""

    def __init__(self, unit_pattern: str = "summitflow-*", since: str = "5 minutes ago") -> None:
        self.unit_pattern = unit_pattern
        self.since = since
        self._seen_hashes: set[str] = set()

    def parse_journal(self) -> list[JournalError]:
        """Run journalctl and return error-level entries."""
        try:
            result = safe_subprocess.run(
                ["journalctl", "--user", "-u", self.unit_pattern,
                 "--since", self.since, "-o", "json", "--no-pager"],
                capture_output=True, text=True, timeout=_JOURNAL_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            logger.warning("journalctl_timeout")
            return []
        except FileNotFoundError:
            logger.warning("journalctl_not_found")
            return []
        except Exception as e:
            logger.error("journal_parse_error", error=str(e))
            return []

        if result.returncode != 0:
            logger.warning("journalctl_failed", returncode=result.returncode, stderr=result.stderr[:200])
            return []

        return self._parse_json_output(result.stdout)

    def _parse_json_output(self, output: str) -> list[JournalError]:
        """Parse newline-delimited JSON output from journalctl."""
        errors: list[JournalError] = []
        for line in output.strip().split("\n"):
            if not line:
                continue
            try:
                error = self._parse_entry(json.loads(line))
                if error:
                    errors.append(error)
            except json.JSONDecodeError:
                logger.debug("skipping_non_json_line", line=line[:50])
        return errors

    def _parse_entry(self, entry: dict[str, str]) -> JournalError | None:
        """Parse a single journal entry dict into a JournalError, or None."""
        try:
            priority = int(entry.get("PRIORITY") or PRIORITY_INFO)
        except ValueError:
            priority = PRIORITY_INFO
        if priority > ERROR_PRIORITY_THRESHOLD:
            return None
        unit = entry.get("_SYSTEMD_UNIT", entry.get("UNIT", "unknown"))
        message = entry.get("MESSAGE", "")
        if not message:
            return None
        timestamp_us = entry.get("__REALTIME_TIMESTAMP")
        try:
            ts = datetime.fromtimestamp(int(timestamp_us) / 1_000_000) if timestamp_us else datetime.now(UTC)
        except (ValueError, OSError):
            ts = datetime.now(UTC)
        return JournalError(unit=unit, message=message, priority=priority, timestamp=ts,
                            error_hash=compute_error_hash(unit, message))

    def get_new_errors(self) -> list[JournalError]:
        """Return errors not yet seen, updating the internal seen-hash set."""
        all_errors = self.parse_journal()
        new_errors = [e for e in all_errors if e.error_hash not in self._seen_hashes]
        for e in new_errors:
            self._seen_hashes.add(e.error_hash)
        if new_errors:
            logger.info("new_errors_detected", count=len(new_errors), total_seen=len(all_errors))
        return new_errors

    def mark_seen(self, error_hash: str) -> None:
        """Mark an error hash as seen (used when loading known errors from DB)."""
        self._seen_hashes.add(error_hash)

    def clear_seen(self) -> None:
        """Clear seen hashes. Use with caution — may cause duplicate task creation."""
        self._seen_hashes.clear()
