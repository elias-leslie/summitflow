"""Private helpers for checkpoint.py — not part of the public API."""

from __future__ import annotations


def create_legacy_branch(task_id: str) -> None:
    """No-op. Per-task branches were fake isolation in a shared checkout;
    parallel coordination is now file-level via st lease. Kept as a callable
    to avoid touching every caller during the cutover."""
    return None
