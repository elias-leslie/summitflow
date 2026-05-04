"""Backup and infrastructure checks for runtime hygiene."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .runtime_hygiene_common import (
    ACTION_COOLDOWN_HOURS,
    BACKUP_FRESH_HOURS,
    HOST_SCOPE,
    INFRA_DRILL_STALE_HOURS,
    INFRA_SOURCE_ID,
    RESTORE_TEST_STALE_HOURS,
    hours_since,
    normalize_action_status,
    record_action,
    status_from_severity,
)


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
    return {
        str(row["source_id"]): row
        for row in deps.backup_store.get_backup_health_summary()
        if isinstance(row, dict) and row.get("source_id")
    }


def backup_state(row: dict[str, Any] | None, *, now: datetime, source_type: str, deps: Any) -> dict[str, Any]:
    if row is None:
        return _missing_backup_state(source_type)
    backup_age = hours_since(row.get("last_success_at"), now=now)
    restore_age = hours_since(row.get("last_restore_tested_at"), now=now)
    drill_age = hours_since(row.get("last_drill_at"), now=now)
    backup_status = row.get("last_backup_status")
    is_fresh = _is_backup_fresh(backup_age, backup_status)
    return {
        "status": "ok" if is_fresh else "stale",
        "source_type": source_type,
        "source_id": row.get("source_id"),
        "backup_age_hours": backup_age,
        "restore_age_hours": restore_age,
        "drill_age_hours": drill_age,
        "is_fresh": is_fresh,
        "restore_validation_ok": _restore_ok(row, source_type, restore_age, drill_age),
        "pending_upload_count": int(row.get("pending_upload_count") or 0),
        "last_backup_status": backup_status,
        "last_success_at": row.get("last_success_at"),
        "last_restore_tested_at": row.get("last_restore_tested_at"),
        "last_restore_test_ok": row.get("last_restore_test_ok"),
        "last_drill_at": row.get("last_drill_at"),
        "last_drill_ok": row.get("last_drill_ok"),
        "last_drill_backup_id": row.get("last_drill_backup_id"),
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
    state = backup_state(backup_rows.get(source_id), now=now, source_type="project", deps=deps)
    fingerprint = f"backup:{source_id}"
    if state["pending_upload_count"] > 0 and state["is_fresh"]:
        state = _drain_pending_uploads(project_id, source_id, backup_rows, latest_runtime_hygiene, actions_taken, now, deps)
    if state["is_fresh"] and state["last_backup_status"] == "completed":
        return state
    if deps._recent_action_succeeded(latest_runtime_hygiene, action_type="backup_catchup", fingerprint=fingerprint, now=now):
        return state
    return _run_project_backup_catchup(project_id, source_id, backup_rows, actions_taken, now, deps)


def infrastructure_protection(
    *,
    backup_rows: dict[str, dict[str, Any]],
    latest_runtime_hygiene: dict[str, Any] | None,
    actions_taken: list[dict[str, Any]],
    now: datetime,
    deps: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str], list[str]]:
    source_id = INFRA_SOURCE_ID
    state = backup_state(backup_rows.get(source_id), now=now, source_type="infrastructure", deps=deps)
    fingerprint = f"backup:{source_id}"
    if not state["is_fresh"] and not deps._recent_action_succeeded(
        latest_runtime_hygiene, action_type="backup_catchup", fingerprint=fingerprint, now=now
    ):
        state = _run_infra_backup_catchup(backup_rows, actions_taken, now, deps)
    issues = _infrastructure_issues(state, source_id, deps)
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


def _missing_backup_state(source_type: str) -> dict[str, Any]:
    return {
        "status": "missing",
        "source_type": source_type,
        "is_fresh": False,
        "restore_validation_ok": False,
        "backup_age_hours": None,
        "restore_age_hours": None,
        "pending_upload_count": 0,
        "last_backup_status": None,
    }


def _is_backup_fresh(backup_age: float | None, backup_status: Any) -> bool:
    return backup_age is not None and backup_age <= BACKUP_FRESH_HOURS and backup_status in {
        "completed",
        "completed_pending_upload",
    }


def _restore_ok(
    row: dict[str, Any],
    source_type: str,
    restore_age: float | None,
    drill_age: float | None,
) -> bool:
    if source_type == "infrastructure":
        return bool(row.get("last_drill_ok") is True and drill_age is not None and drill_age <= INFRA_DRILL_STALE_HOURS)
    return bool(
        row.get("last_restore_test_ok") is True
        and restore_age is not None
        and restore_age <= RESTORE_TEST_STALE_HOURS
    )


def _drain_pending_uploads(
    project_id: str,
    source_id: str,
    backup_rows: dict[str, dict[str, Any]],
    latest_runtime_hygiene: dict[str, Any] | None,
    actions_taken: list[dict[str, Any]],
    now: datetime,
    deps: Any,
) -> dict[str, Any]:
    fingerprint = f"backup:{source_id}"
    if not deps._recent_action_succeeded(latest_runtime_hygiene, action_type="pending_drain", fingerprint=fingerprint, now=now):
        drain_result = deps.drain_pending_backups(dry_run=False)
        record_action(
            actions_taken,
            action_type="pending_drain",
            scope=project_id,
            fingerprint=fingerprint,
            status=normalize_action_status(drain_result.get("status")),
            detail=str(drain_result.get("message") or "pending drain run"),
            result=drain_result,
        )
    backup_rows.update(deps._backup_rows_by_source())
    return backup_state(backup_rows.get(source_id), now=now, source_type="project", deps=deps)


def _run_project_backup_catchup(
    project_id: str,
    source_id: str,
    backup_rows: dict[str, dict[str, Any]],
    actions_taken: list[dict[str, Any]],
    now: datetime,
    deps: Any,
) -> dict[str, Any]:
    backup_result = deps.create_backup(
        project_id=project_id,
        source_id=source_id,
        backup_type="manual",
        note="Runtime hygiene catch-up backup",
    )
    _record_backup_catchup(actions_taken, project_id, source_id, backup_result)
    backup_rows.update(deps._backup_rows_by_source())
    return backup_state(backup_rows.get(source_id), now=now, source_type="project", deps=deps)


def _run_infra_backup_catchup(
    backup_rows: dict[str, dict[str, Any]],
    actions_taken: list[dict[str, Any]],
    now: datetime,
    deps: Any,
) -> dict[str, Any]:
    backup_result = deps.create_backup(
        project_id="infrastructure",
        source_id=INFRA_SOURCE_ID,
        backup_type="manual",
        note="Runtime hygiene catch-up infrastructure backup",
    )
    record_action(
        actions_taken,
        action_type="backup_catchup",
        scope=HOST_SCOPE,
        fingerprint=f"backup:{INFRA_SOURCE_ID}",
        status=normalize_action_status(backup_result.get("status")),
        detail="Triggered infrastructure catch-up backup",
        result=backup_result,
    )
    backup_rows.update(deps._backup_rows_by_source())
    return backup_state(backup_rows.get(INFRA_SOURCE_ID), now=now, source_type="infrastructure", deps=deps)


def _record_backup_catchup(
    actions_taken: list[dict[str, Any]],
    project_id: str,
    source_id: str,
    backup_result: dict[str, Any],
) -> None:
    record_action(
        actions_taken,
        action_type="backup_catchup",
        scope=project_id,
        fingerprint=f"backup:{source_id}",
        status=normalize_action_status(backup_result.get("status")),
        detail=f"Triggered catch-up backup for {source_id}",
        result=backup_result,
    )


def _infrastructure_issues(state: dict[str, Any], source_id: str, deps: Any) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not state["is_fresh"]:
        issues.append(
            deps.host_issue(
                "backup",
                source_id,
                "critical",
                "Infrastructure backup protection is stale or unavailable",
                {"backup": state},
            )
        )
    if not state["restore_validation_ok"]:
        issues.append(
            deps.host_issue(
                "restore_validation",
                source_id,
                "warning",
                "Infrastructure restore drill is stale or failing",
                {"backup": state},
            )
        )
    return issues
