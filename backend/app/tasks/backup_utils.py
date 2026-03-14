"""Utility functions for backup operations."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from typing import Any

from ..logging_config import get_logger
from ..storage.connection import get_connection

logger = get_logger(__name__)


def get_source_path(source_id: str) -> str | None:
    """Get path for a backup source."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT path FROM backup_sources WHERE id = %s",
            (source_id,),
        )
        row = cur.fetchone()
        return row[0] if row and row[0] else None


def get_project_root(project_id: str) -> str | None:
    """Get root_path for a project. Falls back to backup_sources path."""
    # Try backup_sources first (handles non-project sources)
    source_path = get_source_path(project_id)
    if source_path:
        return source_path

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT root_path FROM projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()
        return row[0] if row and row[0] else None


def _parse_backup_line(line: str, result: dict[str, Any]) -> None:
    """Parse a single line of backup.sh output and update result in place."""
    line = line.strip()

    if line.startswith("Size:"):
        result["total_bytes"] = parse_size(line.split(":", 1)[1].strip())
        return

    if line.startswith("DB Size:"):
        result["db_bytes"] = parse_size(line.split(":", 1)[1].strip())
        return

    if line.startswith("Location:"):
        result["location"] = line.split(":", 1)[1].strip()
        return

    if line.startswith("Archive:"):
        result["archive_name"] = line.split(":", 1)[1].strip()
        return

    if line.startswith("Pending:"):
        result["pending_path"] = line.split(":", 1)[1].strip()
        return

    if not line.startswith("Verification:"):
        return

    json_str = line.split(":", 1)[1].strip()
    try:
        result["verification"] = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        logger.warning("failed_to_parse_verification_json", raw=json_str[:200])


def parse_backup_output(output: str) -> dict[str, Any]:
    """Parse backup.sh output for size, location, and verification info."""
    result: dict[str, Any] = {}
    for line in output.split("\n"):
        _parse_backup_line(line, result)
    return result


def _parse_bytes_literal(size_str: str) -> int | None:
    """Parse a size string containing the word 'bytes'."""
    try:
        return int(size_str.replace("bytes", "").strip())
    except ValueError:
        return None


def _parse_suffix_size(size_str: str) -> int | None:
    """Parse a size string with a unit suffix like K, M, G, T."""
    multipliers = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
    for suffix, mult in multipliers.items():
        if not size_str.endswith(suffix):
            continue
        try:
            return int(float(size_str[:-1]) * mult)
        except ValueError:
            return None
    return None


def parse_size(size_str: str) -> int | None:
    """Parse size string like '123M', '1.5G', or '123456 bytes'."""
    size_str = size_str.strip()

    if "bytes" in size_str:
        return _parse_bytes_literal(size_str)

    suffix_result = _parse_suffix_size(size_str)
    if suffix_result is not None:
        return suffix_result

    try:
        return int(size_str)
    except ValueError:
        return None


def build_script_error_message(result: subprocess.CompletedProcess[str]) -> str:
    """Build an informative error message from a failed subprocess result."""
    stderr_clean = result.stderr or ""
    stderr_lines = [ln for ln in stderr_clean.splitlines() if not ln.strip().startswith("putting file")]
    stderr_filtered = "\n".join(stderr_lines).strip()
    stdout_tail = (result.stdout or "")[-500:].strip()
    parts = [f"rc={result.returncode}"]
    if stderr_filtered:
        parts.append(f"stderr: {stderr_filtered}")
    if stdout_tail:
        parts.append(f"stdout(tail): {stdout_tail}")
    return " | ".join(parts) if any([stderr_filtered, stdout_tail]) else "Unknown error"


def build_verification_kwargs(verification: dict[str, Any]) -> dict[str, Any]:
    """Extract verification fields into update_backup_status kwargs."""
    vkw: dict[str, Any] = {
        "verified": verification.get("verified"),
        "verified_at": verification.get("verified_at"),
        "checksum": verification.get("checksum"),
        "verification_json": verification,
    }
    total = verification.get("total_files")
    if total is not None:
        vkw["total_files"] = int(total)
    return vkw


_FREQUENCY_DELTAS: dict[str, timedelta] = {
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
    "monthly": timedelta(days=30),
}


def calculate_next_run(frequency: str) -> datetime:
    """Calculate next run time based on frequency."""
    now = datetime.now(UTC)
    delta = _FREQUENCY_DELTAS.get(frequency, timedelta(days=1))
    return now + delta
