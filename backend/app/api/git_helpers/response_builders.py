"""Response builders for git API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models.git_models import SyncResult


def build_sync_response_from_result(result: SyncResult) -> dict[str, int]:
    """Build a sync response from a single result.

    Args:
        result: The sync result to build response from

    Returns:
        Dict with success, failed, and skipped counts
    """
    return {
        "success": 1 if result.status in ["updated", "up_to_date"] else 0,
        "failed": 1 if result.status == "failed" else 0,
        "skipped": 1 if result.status == "skipped" else 0,
    }


def aggregate_sync_results(results: list[SyncResult]) -> dict[str, int]:
    """Aggregate multiple sync results into counts.

    Args:
        results: List of sync results to aggregate

    Returns:
        Dict with success, failed, and skipped counts
    """
    success = 0
    failed = 0
    skipped = 0

    for result in results:
        if result.status in ["up_to_date", "updated"]:
            success += 1
        elif result.status == "failed":
            failed += 1
        elif result.status == "skipped":
            skipped += 1

    return {"success": success, "failed": failed, "skipped": skipped}
