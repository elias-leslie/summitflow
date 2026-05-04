"""Runtime hygiene orchestration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .runtime_hygiene_common import PROJECTS, WORKFLOW_NAME, json_safe, now_utc
from .runtime_hygiene_issues import unresolved_issue_summary


def run_runtime_hygiene(deps: Any) -> dict[str, Any]:
    started_at = now_utc()
    latest_runtime_hygiene = deps._latest_runtime_hygiene_run()
    try:
        result = _run_success_path(started_at, latest_runtime_hygiene, deps)
        _record_success(started_at, result, deps)
        return result
    except Exception as exc:
        deps.logger.exception("runtime_hygiene_failed")
        _record_failure(started_at, exc, deps)
        raise


def _run_success_path(
    started_at: datetime,
    latest_runtime_hygiene: dict[str, Any] | None,
    deps: Any,
) -> dict[str, Any]:
    backup_rows = deps._backup_rows_by_source()
    host, host_actions, host_issues, host_created, host_reused = deps._host_pressure(
        latest_runtime_hygiene=latest_runtime_hygiene,
        now=started_at,
    )
    infra_summary, infra_issues, infra_created, infra_reused = deps._infrastructure_protection(
        backup_rows=backup_rows,
        latest_runtime_hygiene=latest_runtime_hygiene,
        actions_taken=host_actions,
        now=started_at,
    )
    return _build_result(
        host,
        host_actions,
        [*host_issues, *infra_issues],
        [*host_created, *infra_created],
        [*host_reused, *infra_reused],
        _target_results(backup_rows, latest_runtime_hygiene, started_at, deps),
        infra_summary,
    )


def _target_results(
    backup_rows: dict[str, dict[str, Any]],
    latest_runtime_hygiene: dict[str, Any] | None,
    started_at: datetime,
    deps: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str], list[str], list[dict[str, Any]]]:
    targets: dict[str, Any] = {}
    issues: list[dict[str, Any]] = []
    created: list[str] = []
    reused: list[str] = []
    actions: list[dict[str, Any]] = []
    for project_id in PROJECTS:
        target_summary, target_issues, created_ids, reused_ids = deps._project_target(
            project_id,
            backup_rows=backup_rows,
            latest_runtime_hygiene=latest_runtime_hygiene,
            now=started_at,
        )
        targets[project_id] = target_summary
        issues.extend(target_issues)
        created.extend(created_ids)
        reused.extend(reused_ids)
        actions.extend(target_summary.get("actions_taken") or [])
    return targets, issues, created, reused, actions


def _build_result(
    host: dict[str, Any],
    host_actions: list[dict[str, Any]],
    base_issues: list[dict[str, Any]],
    base_created: list[str],
    base_reused: list[str],
    target_data: tuple[dict[str, Any], list[dict[str, Any]], list[str], list[str], list[dict[str, Any]]],
    infra_summary: dict[str, Any],
) -> dict[str, Any]:
    targets, target_issues, target_created, target_reused, target_actions = target_data
    all_issues = [*base_issues, *target_issues]
    actions_taken = [*host_actions, *target_actions]
    return {
        "status": "partial" if all_issues else "success",
        "host": host,
        "infrastructure": infra_summary,
        "targets": targets,
        "actions_taken": actions_taken,
        "unresolved_issues": unresolved_issue_summary(all_issues),
        "created_task_ids": sorted(set([*base_created, *target_created])),
        "reused_task_ids": sorted(set([*base_reused, *target_reused])),
        "skipped_reasons": [
            action["detail"]
            for action in actions_taken
            if action.get("status") == "skipped"
        ],
    }


def _record_success(started_at: datetime, result: dict[str, Any], deps: Any) -> None:
    deps.maintenance_store.record_maintenance_run(
        WORKFLOW_NAME,
        result["status"],
        started_at=started_at,
        finished_at=now_utc(),
        rows_cleaned=len(result["created_task_ids"]),
        summary=json_safe(result),
    )


def _record_failure(started_at: datetime, exc: Exception, deps: Any) -> None:
    deps.maintenance_store.record_maintenance_run(
        WORKFLOW_NAME,
        "failed",
        started_at=started_at,
        finished_at=now_utc(),
        rows_cleaned=0,
        summary={
            "status": "failed",
            "actions_taken": [],
            "unresolved_issues": [],
            "created_task_ids": [],
            "reused_task_ids": [],
            "skipped_reasons": [],
        },
        error_message=str(exc),
    )
