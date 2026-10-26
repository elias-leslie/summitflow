"""Backup and infrastructure checks for runtime hygiene.

Backups are two host jobs now (btrbk points every 4 hours and one daily Google Drive copy), so hygiene reads
their health from ``backup_overview`` and only reports. It never starts a backup: the timer does that.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .runtime_hygiene_common import (
    ACTION_COOLDOWN_HOURS,
    INFRA_SOURCE_ID,
    hours_since,
    status_from_severity,
)

HOST_ROW = "host"
# backup_overview problem keys: a recovery point is missing, or the Drive copy could not be verified.
_STALE_KEYS = {"local-missing", "offsite-missing"}
_UNVERIFIED_KEYS = {"offsite-check", "offsite-spot-restore"}


def latest_run(workflow_name: str, deps: Any) -> dict[str, Any] | None:
    runs = deps.maintenance_store.list_maintenance_runs(limit=1, workflow_name=workflow_name)
    return runs[0] if runs else None


def run_started_within(workflow_name: str, *, hours: float, now: datetime, deps: Any) -> bool:
    latest = latest_run(workflow_name, deps)
    if latest is None:
        return False
    started_at = deps._coerce_datetime(latest.get("started_at"))
    return bool(started_at and now - started_at <= timedelta(hours=hours))


def recent_action_succeeded(
    latest_run_data: dict[str, Any] | None,
    *,
    action_type: str,
    fingerprint: str,
    now: datetime,
    deps: Any,
) -> bool:
    if latest_run_data is None:
        return False
    started_at = deps._coerce_datetime(latest_run_data.get("started_at"))
    cooldown = ACTION_COOLDOWN_HOURS.get(action_type)
    if started_at is None or cooldown is None or now - started_at > timedelta(hours=cooldown):
        return False
    actions = _latest_actions(latest_run_data)
    return any(_is_matching_completed_action(action, action_type, fingerprint) for action in actions)


def backup_rows_by_source(deps: Any) -> dict[str, dict[str, Any]]:
    """One host-level row, read from the backup overview."""
    from . import backup_offsite, backup_overview

    problems = {problem["key"] for problem in backup_overview.health_problems()}
    return {
        HOST_ROW: {
            "source_id": HOST_ROW,
            "last_success_at": backup_offsite.read_state().get("last_success_at"),
            "stale": bool(problems & _STALE_KEYS),
            "unverified": bool(problems & _UNVERIFIED_KEYS),
        }
    }


def backup_state(row: dict[str, Any] | None, *, now: datetime, source_type: str, deps: Any) -> dict[str, Any]:
    if row is None:
        return {
            "status": "missing",
            "source_type": source_type,
            "is_fresh": False,
            "restore_validation_ok": False,
            "backup_age_hours": None,
            "pending_upload_count": 0,
            "last_backup_status": None,
        }
    is_fresh = not row.get("stale")
    return {
        "status": "ok" if is_fresh else "stale",
        "source_type": source_type,
        "source_id": row.get("source_id"),
        "backup_age_hours": hours_since(row.get("last_success_at"), now=now),
        "is_fresh": is_fresh,
        "restore_validation_ok": not row.get("unverified"),
        "pending_upload_count": 0,
        "last_backup_status": "completed" if is_fresh else "failed",
        "last_success_at": row.get("last_success_at"),
    }


def ensure_backup_fresh(
    *,
    project_id: str,
    source_id: str,
    backup_rows: dict[str, dict[str, Any]],
    latest_runtime_hygiene: dict[str, Any] | None,
    actions_taken: list[dict[str, Any]],
    now: datetime,
    deps: Any,
) -> dict[str, Any]:
    return backup_state(backup_rows.get(HOST_ROW), now=now, source_type="project", deps=deps)


def infrastructure_protection(
    *,
    backup_rows: dict[str, dict[str, Any]],
    latest_runtime_hygiene: dict[str, Any] | None,
    actions_taken: list[dict[str, Any]],
    now: datetime,
    deps: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str], list[str]]:
    state = backup_state(backup_rows.get(HOST_ROW), now=now, source_type="infrastructure", deps=deps)
    issues = _infrastructure_issues(state, INFRA_SOURCE_ID, deps)
    created_task_ids, reused_task_ids = deps.persist_issues(issues, deps)
    return {"status": status_from_severity(deps.highest_severity(issues, deps)), "backup": state}, issues, created_task_ids, reused_task_ids


def _latest_actions(latest_run_data: dict[str, Any]) -> list[Any]:
    summary = latest_run_data.get("summary") if isinstance(latest_run_data.get("summary"), dict) else {}
    actions = summary.get("actions_taken") if isinstance(summary, dict) else []
    return actions if isinstance(actions, list) else []


def _is_matching_completed_action(action: Any, action_type: str, fingerprint: str) -> bool:
    return (
        isinstance(action, dict)
        and action.get("type") == action_type
        and action.get("fingerprint") == fingerprint
        and action.get("status") == "completed"
    )


def _infrastructure_issues(state: dict[str, Any], source_id: str, deps: Any) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not state["is_fresh"]:
        issues.append(
            deps.host_issue("backup", source_id, "critical", "Backup recovery point is missing", {"backup": state})
        )
    if not state["restore_validation_ok"]:
        issues.append(
            deps.host_issue("restore_validation", source_id, "warning", "Google Drive backup check or test restore is failing", {"backup": state})
        )
    return issues
