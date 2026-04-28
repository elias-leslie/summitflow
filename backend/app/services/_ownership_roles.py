"""Ownership role helpers shared by pulse and session diagnostics."""

from __future__ import annotations

from typing import Any


def is_read_only_owner(record: dict[str, Any]) -> bool:
    """Return true for telemetry rows that observed reads but no write intent."""
    if str(record.get("scope_confidence") or "") != "observed_read":
        return False
    for key in ("declared_scope_paths", "observed_write_paths"):
        values = record.get(key)
        if isinstance(values, list) and any(str(value).strip() for value in values):
            return False
    return True
