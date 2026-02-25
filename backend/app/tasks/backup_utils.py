"""Utility functions for backup operations."""

from __future__ import annotations

import json
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


def parse_backup_output(output: str) -> dict[str, Any]:
    """Parse backup.sh output for size, location, and verification info."""
    result: dict[str, Any] = {}

    for line in output.split("\n"):
        line = line.strip()
        if line.startswith("Size:"):
            size_str = line.split(":", 1)[1].strip()
            result["total_bytes"] = parse_size(size_str)
        elif line.startswith("DB Size:"):
            size_str = line.split(":", 1)[1].strip()
            result["db_bytes"] = parse_size(size_str)
        elif line.startswith("Location:"):
            result["location"] = line.split(":", 1)[1].strip()
        elif line.startswith("Verification:"):
            json_str = line.split(":", 1)[1].strip()
            try:
                result["verification"] = json.loads(json_str)
            except (json.JSONDecodeError, ValueError):
                logger.warning("failed_to_parse_verification_json", raw=json_str[:200])

    return result


def parse_size(size_str: str) -> int | None:
    """Parse size string like '123M', '1.5G', or '123456 bytes'."""
    size_str = size_str.strip()

    if "bytes" in size_str:
        try:
            return int(size_str.replace("bytes", "").strip())
        except ValueError:
            return None

    multipliers = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}

    for suffix, mult in multipliers.items():
        if size_str.endswith(suffix):
            try:
                return int(float(size_str[:-1]) * mult)
            except ValueError:
                return None

    try:
        return int(size_str)
    except ValueError:
        return None


def calculate_next_run(frequency: str) -> datetime:
    """Calculate next run time based on frequency."""
    now = datetime.now(UTC)

    if frequency == "daily":
        return now + timedelta(days=1)
    elif frequency == "weekly":
        return now + timedelta(weeks=1)
    elif frequency == "monthly":
        return now + timedelta(days=30)
    else:
        # Default to daily
        return now + timedelta(days=1)
