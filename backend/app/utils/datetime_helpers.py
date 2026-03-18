"""Shared datetime parsing utilities."""

from __future__ import annotations

from datetime import UTC, datetime


def parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse an ISO datetime string, normalizing timezone to UTC.

    Handles trailing 'Z' suffix and naive datetimes (assumed UTC).

    Args:
        value: ISO datetime string, or None.

    Returns:
        Parsed UTC datetime, or None if value is falsy or unparseable.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
