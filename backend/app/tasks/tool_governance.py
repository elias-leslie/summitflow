"""Scheduled st tool-governance scan."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.storage import maintenance_runs as maintenance_store

TOOL_GOVERNANCE_WORKFLOW = "tool_governance"
DEFAULT_SCAN_HOURS = 24
DEFAULT_SCAN_LIMIT = 20


def _manifest_savings(cost: dict[str, Any]) -> int:
    costs = {item.get("density"): item for item in cost.get("manifest_costs", [])}
    full = int((costs.get("full") or {}).get("tokens_approx") or 0)
    core = int((costs.get("core") or {}).get("tokens_approx") or 0)
    return max(0, full - core)


def _run_summary(audit: dict[str, Any], cost: dict[str, Any], *, emit_feedback: bool) -> dict[str, Any]:
    audit_summary = audit.get("summary") or {}
    return {
        "workflow": TOOL_GOVERNANCE_WORKFLOW,
        "status": "completed",
        "hours": audit.get("window_hours", DEFAULT_SCAN_HOURS),
        "audit_finding_groups": int(audit_summary.get("finding_groups") or 0),
        "audit_events": int(audit_summary.get("events") or 0),
        "manifest_saved_tokens_approx": _manifest_savings(cost),
        "request_hotspots": len(cost.get("request_hotspots") or []),
        "tool_output_hotspots": len(cost.get("tool_output_hotspots") or []),
        "feedback_emitted": emit_feedback,
    }


def run_tool_governance_scan(
    *,
    hours: int = DEFAULT_SCAN_HOURS,
    limit: int = DEFAULT_SCAN_LIMIT,
    emit_feedback: bool = True,
) -> dict[str, Any]:
    """Run deterministic tool-governance checks and optionally emit deduped feedback."""
    from cli.commands.tools import (
        _emit_feedback_for_audit,
        _emit_feedback_for_cost,
        _fetch_audit_metrics,
        _fetch_cost_metrics,
    )

    started_at = datetime.now(UTC)
    audit = _fetch_audit_metrics(hours, limit)
    cost = _fetch_cost_metrics(hours, limit)
    if emit_feedback:
        _emit_feedback_for_audit(audit)
        _emit_feedback_for_cost(cost)
    result = _run_summary(audit, cost, emit_feedback=emit_feedback)
    maintenance_store.record_maintenance_run(
        TOOL_GOVERNANCE_WORKFLOW,
        "completed",
        started_at=started_at,
        finished_at=datetime.now(UTC),
        rows_cleaned=int(result["audit_events"]),
        summary=result,
    )
    return result
