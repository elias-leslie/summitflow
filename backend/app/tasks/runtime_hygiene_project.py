"""Project-level runtime hygiene checks."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .runtime_hygiene_backups import backup_state
from .runtime_hygiene_common import (
    JOURNAL_LOOKBACK,
    JOURNAL_PATTERNS,
    JOURNAL_TASK_LIMIT,
    MAX_VACUUM_TABLES_PER_DB,
    TARGET_BACKUP_SOURCES,
    normalize_action_status,
    record_action,
    status_from_severity,
)


def journal_findings(project_id: str, deps: Any) -> dict[str, Any]:
    pattern = JOURNAL_PATTERNS[project_id]
    monitor = deps.SystemdMonitor(unit_pattern=pattern, since=JOURNAL_LOOKBACK)
    unique: dict[str, Any] = {}
    for error in monitor.parse_journal():
        unique.setdefault(error.error_hash, error)
    return {
        "status": "issues" if unique else "ok",
        "pattern": pattern,
        "issue_count": len(unique),
        "created_task_ids": [],
        "errors": [_journal_error(error) for error in list(unique.values())[:JOURNAL_TASK_LIMIT]],
    }


def project_target(
    project_id: str,
    *,
    backup_rows: dict[str, dict[str, Any]],
    latest_runtime_hygiene: dict[str, Any] | None,
    now: datetime,
    deps: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str], list[str]]:
    actions_taken: list[dict[str, Any]] = []
    source_id = TARGET_BACKUP_SOURCES[project_id]
    backup = _freshened_backup(project_id, source_id, backup_rows, latest_runtime_hygiene, actions_taken, now, deps)
    journal = deps._journal_findings(project_id)
    issues = _journal_issues(project_id, journal, deps)
    issues.extend(_backup_issues(project_id, source_id, backup, deps))
    bloat = _bloat_check(project_id, backup, latest_runtime_hygiene, actions_taken, now, deps)
    issues.extend(_bloat_issues(project_id, backup, bloat, deps))
    created_task_ids, reused_task_ids = deps.persist_issues(issues, deps)
    journal["created_task_ids"] = _journal_task_ids(issues)
    return (
        _target_summary(project_id, backup, journal, bloat, actions_taken, issues, created_task_ids, reused_task_ids, deps),
        issues,
        created_task_ids,
        reused_task_ids,
    )


def _journal_error(error: Any) -> dict[str, Any]:
    return {
        "unit": error.unit,
        "priority": error.priority,
        "error_hash": error.error_hash,
        "timestamp": error.timestamp.isoformat(),
        "message": error.message[:300],
    }


def _freshened_backup(
    project_id: str,
    source_id: str,
    backup_rows: dict[str, dict[str, Any]],
    latest_runtime_hygiene: dict[str, Any] | None,
    actions_taken: list[dict[str, Any]],
    now: datetime,
    deps: Any,
) -> dict[str, Any]:
    state = backup_state(backup_rows.get(source_id), now=now, source_type="project", deps=deps)
    if not state["is_fresh"] or state["pending_upload_count"] > 0:
        return deps._ensure_backup_fresh(
            project_id=project_id,
            source_id=source_id,
            backup_rows=backup_rows,
            latest_runtime_hygiene=latest_runtime_hygiene,
            actions_taken=actions_taken,
            now=now,
        )
    return state


def _journal_issues(project_id: str, journal: dict[str, Any], deps: Any) -> list[dict[str, Any]]:
    if int(journal.get("issue_count") or 0) <= 0:
        return []
    return [
        deps.project_issue(
            project_id,
            "journal",
            "journal-errors",
            "warning",
            f"Investigate recent {project_id} runtime journal errors",
            {"journal": {"pattern": journal.get("pattern"), "issue_count": journal.get("issue_count"), "errors": list(journal.get("errors") or [])}},
        )
    ]


def _backup_issues(project_id: str, source_id: str, state: dict[str, Any], deps: Any) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not state["is_fresh"]:
        issues.append(
            deps.project_issue(project_id, "backup", source_id, "critical", f"{project_id} backup protection is stale or unavailable", {"backup": state})
        )
    elif state["pending_upload_count"] > 0:
        issues.append(
            deps.project_issue(project_id, "backup", source_id, "warning", f"{project_id} backup is still pending upload after drain attempt", {"backup": state})
        )
    if not state["restore_validation_ok"]:
        issues.append(
            deps.project_issue(project_id, "restore_validation", source_id, "warning", f"{project_id} restore validation is stale or failing", {"backup": state})
        )
    return issues


def _bloat_check(
    project_id: str,
    backup: dict[str, Any],
    latest_runtime_hygiene: dict[str, Any] | None,
    actions_taken: list[dict[str, Any]],
    now: datetime,
    deps: Any,
) -> dict[str, Any]:
    bloat = deps._query_bloat_candidates(project_id)
    if bloat.get("status") == "unavailable":
        return bloat
    candidates = _sorted_bloat_candidates(bloat)
    vacuumed, skipped = _remediate_bloat(project_id, backup, candidates, latest_runtime_hygiene, actions_taken, now, deps)
    if vacuumed or (candidates and not vacuumed):
        refreshed = deps._query_bloat_candidates(project_id)
        if refreshed.get("status") != "unavailable":
            bloat = refreshed
    if skipped:
        bloat["skipped_candidates"] = skipped
    if vacuumed:
        bloat["vacuumed"] = vacuumed
    return bloat


def _sorted_bloat_candidates(bloat: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = list(bloat.get("candidates") or [])
    return sorted(
        candidates,
        key=lambda item: (item.get("dead_bytes") or 0, item.get("dead_pct") or 0.0),
        reverse=True,
    )


def _remediate_bloat(
    project_id: str,
    backup: dict[str, Any],
    candidates: list[dict[str, Any]],
    latest_runtime_hygiene: dict[str, Any] | None,
    actions_taken: list[dict[str, Any]],
    now: datetime,
    deps: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not candidates:
        return [], []
    if not (backup["is_fresh"] and backup["last_backup_status"] == "completed"):
        return [], [{**candidate, "skip_reason": "backup_prerequisite_not_satisfied"} for candidate in candidates]
    return _vacuum_candidates(project_id, candidates, latest_runtime_hygiene, actions_taken, now, deps)


def _vacuum_candidates(
    project_id: str,
    candidates: list[dict[str, Any]],
    latest_runtime_hygiene: dict[str, Any] | None,
    actions_taken: list[dict[str, Any]],
    now: datetime,
    deps: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    vacuumed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for candidate in candidates[:MAX_VACUUM_TABLES_PER_DB]:
        fingerprint = f"vacuum:{project_id}:{candidate['table_ref']}"
        if deps._recent_action_succeeded(latest_runtime_hygiene, action_type="vacuum_analyze", fingerprint=fingerprint, now=now):
            skipped.append({**candidate, "skip_reason": "recent_vacuum"})
            continue
        vacuum_result = deps._vacuum_analyze_table(project_id, str(candidate["schema"]), str(candidate["table"]))
        vacuumed.append({**candidate, **vacuum_result})
        _record_vacuum_action(actions_taken, project_id, candidate, fingerprint, vacuum_result)
    return vacuumed, skipped


def _record_vacuum_action(
    actions_taken: list[dict[str, Any]],
    project_id: str,
    candidate: dict[str, Any],
    fingerprint: str,
    vacuum_result: dict[str, Any],
) -> None:
    record_action(
        actions_taken,
        action_type="vacuum_analyze",
        scope=project_id,
        fingerprint=fingerprint,
        status=normalize_action_status(vacuum_result.get("status")),
        detail=f"VACUUM ANALYZE {candidate['schema']}.{candidate['table']}",
        result=vacuum_result,
    )


def _bloat_issues(project_id: str, backup: dict[str, Any], bloat: dict[str, Any], deps: Any) -> list[dict[str, Any]]:
    if bloat.get("status") == "unavailable":
        return [deps.project_issue(project_id, "db_access", "db-access", "warning", f"{project_id} DB bloat check is unavailable", {"bloat": bloat})]
    issues = []
    for candidate in list(bloat.get("candidates") or []):
        severity = candidate.get("severity") or "warning"
        issues.append(
            deps.project_issue(
                project_id,
                "db_bloat",
                str(candidate["table_ref"]),
                severity if severity in {"warning", "critical"} else "warning",
                f"{project_id} table {candidate['table_ref']} still shows actionable DB bloat",
                {"bloat": candidate, "backup": backup},
            )
        )
    return issues


def _journal_task_ids(issues: list[dict[str, Any]]) -> list[str]:
    return [
        str(issue.get("task_id"))
        for issue in issues
        if issue.get("issue_type") == "journal" and issue.get("task_id")
    ]


def _target_summary(
    project_id: str,
    backup: dict[str, Any],
    journal: dict[str, Any],
    bloat: dict[str, Any],
    actions_taken: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    created_task_ids: list[str],
    reused_task_ids: list[str],
    deps: Any,
) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "status": status_from_severity(deps.highest_severity(issues, deps)),
        "backup": backup,
        "journal": journal,
        "bloat": bloat,
        "actions_taken": actions_taken,
        "unresolved_issue_count": len(issues),
        "created_task_ids": created_task_ids,
        "reused_task_ids": reused_task_ids,
    }
