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


def _run_summary(
    adoption: dict[str, Any],
    audit: dict[str, Any],
    cost: dict[str, Any],
    *,
    emit_feedback: bool,
    feedback_errors: list[dict[str, str]],
) -> dict[str, Any]:
    adoption_summary = adoption.get("summary") or {}
    audit_summary = audit.get("summary") or {}
    status = "partial" if feedback_errors else "completed"
    return {
        "workflow": TOOL_GOVERNANCE_WORKFLOW,
        "status": status,
        "hours": audit.get("window_hours", DEFAULT_SCAN_HOURS),
        "shell_tool_events": int(adoption_summary.get("shell_tool_events") or 0),
        "st_commands": int(adoption_summary.get("st_commands") or 0),
        "st_command_rate": float(adoption_summary.get("st_command_rate") or 0.0),
        "raw_quality_commands": int(adoption_summary.get("raw_quality_commands") or 0),
        "audit_finding_groups": int(audit_summary.get("finding_groups") or 0),
        "audit_events": int(audit_summary.get("events") or 0),
        "manifest_saved_tokens_approx": _manifest_savings(cost),
        "request_hotspots": len(cost.get("request_hotspots") or []),
        "tool_output_hotspots": len(cost.get("tool_output_hotspots") or []),
        "feedback_emitted": emit_feedback,
        "feedback_errors": feedback_errors,
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
        _fetch_adoption_metrics,
        _fetch_audit_metrics,
        _fetch_cost_metrics,
    )

    started_at = datetime.now(UTC)
    adoption = _fetch_adoption_metrics(hours, limit)
    audit = _fetch_audit_metrics(hours, limit)
    cost = _fetch_cost_metrics(hours, limit)
    feedback_errors: list[dict[str, str]] = []
    if emit_feedback:
        for source, emit in (("audit", _emit_feedback_for_audit), ("cost", _emit_feedback_for_cost)):
            try:
                emit(audit if source == "audit" else cost)
            except Exception as exc:
                feedback_errors.append({"source": source, "error": str(exc)[-500:]})
    result = _run_summary(
        adoption,
        audit,
        cost,
        emit_feedback=emit_feedback,
        feedback_errors=feedback_errors,
    )
    maintenance_store.record_maintenance_run(
        TOOL_GOVERNANCE_WORKFLOW,
        result["status"],
        started_at=started_at,
        finished_at=datetime.now(UTC),
        rows_cleaned=int(result["audit_events"]),
        summary=result,
        error_message="; ".join(item["error"] for item in feedback_errors) if feedback_errors else None,
    )
    return result
