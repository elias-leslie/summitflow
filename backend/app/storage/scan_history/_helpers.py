"""Internal helpers for scan history storage."""

from __future__ import annotations

from typing import Any

from ..explorer_entries import _to_iso_string


def row_to_scan(row: tuple[Any, ...]) -> dict[str, Any]:
    """Convert a database row to a scan dict."""
    return {
        "id": row[0],
        "project_id": row[1],
        "scan_type": row[2],
        "triggered_by": row[3],
        "triggered_by_session": row[4],
        "triggered_by_user": row[5],
        "trigger_context": row[6] if row[6] else {},
        "started_at": _to_iso_string(row[7]),
        "completed_at": _to_iso_string(row[8]),
        "duration_ms": row[9],
        "status": row[10],
        "error_message": row[11],
        "metrics": row[12] if row[12] else {},
        "entries_found": row[13] or 0,
        "entries_saved": row[14] or 0,
        "previous_scan_id": row[15],
        "metrics_delta": row[16] if row[16] else {},
        "created_at": _to_iso_string(row[17]),
    }


def compute_metrics_delta(
    metrics: dict[str, Any],
    entries_found: int,
    entries_saved: int,
    prev_metrics: dict[str, Any],
    prev_entries_found: int,
    prev_entries_saved: int,
) -> dict[str, Any]:
    """Compute delta between current and previous scan metrics."""
    delta: dict[str, Any] = {
        "entries_found": entries_found - prev_entries_found,
        "entries_saved": entries_saved - prev_entries_saved,
    }
    for key in metrics:
        if key in prev_metrics and isinstance(metrics[key], int | float):
            delta[key] = metrics[key] - prev_metrics.get(key, 0)
    return delta


def compute_comparison_delta(
    before: dict[str, Any],
    after: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, float]]:
    """Compute deltas and percentage changes between two scan records."""
    before_metrics = before.get("metrics", {})
    after_metrics = after.get("metrics", {})

    delta: dict[str, Any] = {
        "entries_found": after.get("entries_found", 0) - before.get("entries_found", 0),
        "entries_saved": after.get("entries_saved", 0) - before.get("entries_saved", 0),
    }
    delta_pct: dict[str, float] = {}

    all_keys = set(before_metrics.keys()) | set(after_metrics.keys())
    for key in all_keys:
        before_val = before_metrics.get(key, 0)
        after_val = after_metrics.get(key, 0)
        if isinstance(before_val, int | float) and isinstance(after_val, int | float):
            delta[key] = after_val - before_val
            if before_val != 0:
                delta_pct[key] = round((after_val - before_val) / before_val * 100, 2)

    if before.get("entries_found", 0) > 0:
        delta_pct["entries_found"] = round(
            delta["entries_found"] / before["entries_found"] * 100, 2
        )

    return delta, delta_pct


def classify_complexity_trend(weekly_data: dict[str, Any]) -> str:
    """Classify complexity trend from weekly aggregation data."""
    if "recent" not in weekly_data or "previous" not in weekly_data:
        return "unknown"
    diff = weekly_data["recent"] - weekly_data["previous"]
    if diff < -0.1:
        return "improving"
    if diff > 0.1:
        return "degrading"
    return "stable"


def build_triggers_breakdown(
    trigger_rows: list[tuple[Any, ...]],
    total_scans: int,
) -> tuple[list[dict[str, Any]], str | None]:
    """Build triggers breakdown list and find most active trigger."""
    triggers_breakdown: list[dict[str, Any]] = []
    most_active_trigger: str | None = None
    for i, row in enumerate(trigger_rows):
        if i == 0:
            most_active_trigger = row[0]
        pct = round(row[1] / total_scans * 100, 1) if total_scans > 0 else 0.0
        triggers_breakdown.append({"trigger": row[0], "count": row[1], "percentage": pct})
    return triggers_breakdown, most_active_trigger
