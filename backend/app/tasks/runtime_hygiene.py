"""Daily runtime hygiene audit for SummitFlow and Agent Hub.

Combines existing maintenance, backup, and self-healing surfaces into one
backup-aware daily audit that:
- checks host disk / memory / CPU pressure
- checks backup freshness and restore-validation freshness
- checks DB bloat for SummitFlow + Agent Hub
- scans recent systemd journal errors for both projects
- runs only safe bounded remediation steps
- creates or refreshes self-contained follow-up tasks when deeper work remains
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import psutil
import psycopg
from psycopg import sql

from app.logging_config import get_logger
from app.services.explorer.types.database_config import get_db_url_for_project
from app.services.resource_monitor import get_cpu_usage, get_disk_usages, get_memory_usage
from app.services.self_healing.monitor import SystemdMonitor
from app.storage import backups as backup_store
from app.storage import maintenance_runs as maintenance_store
from app.storage import tasks as task_store
from app.storage.connection import get_cursor
from app.storage.task_spirit import (
    approve_plan,
    create_task_spirit,
    get_task_spirit,
    update_task_spirit,
)
from app.tasks.autonomous._subtask_builder import create_single_subtask_with_steps
from app.tasks.backup_drain import drain_pending_backups
from app.tasks.backup_executor import create_backup
from app.tasks.host_retention import cleanup_host_artifacts

logger = get_logger(__name__)

_WORKFLOW_NAME = "runtime_hygiene"
_PROJECTS: tuple[str, ...] = ("summitflow", "agent-hub")
_JOURNAL_PATTERNS = {
    "summitflow": "summitflow-*",
    "agent-hub": "agent-hub-*",
}
_TARGET_BACKUP_SOURCES = {
    "summitflow": "summitflow",
    "agent-hub": "agent-hub",
}
_INFRA_SOURCE_ID = "infrastructure"
_ROOT_MOUNT = "/"
_HOST_SCOPE = "host"
_RUNTIME_CTX_KEY = "runtime_hygiene"
_DONE_WHEN = [
    "The runtime_hygiene fingerprint in task context no longer reproduces, or the issue is explicitly accepted with evidence.",
    "Any safe verification for this issue is captured in the task log or description before closeout.",
    "No unrelated remediation is bundled into the fix.",
]

_DISK_WARN_PERCENT = 80.0
_DISK_CRIT_PERCENT = 90.0
_DISK_REMEDIATE_FREE_GB = 15.0
_DISK_CRIT_FREE_GB = 10.0
_MEMORY_WARN_PERCENT = 85.0
_MEMORY_CRIT_PERCENT = 95.0
_CPU_WARN_PERCENT = 80.0
_CPU_CRIT_PERCENT = 90.0

_BACKUP_FRESH_HOURS = 36.0
_INFRA_DRILL_STALE_HOURS = 48.0
_RESTORE_TEST_STALE_HOURS = 8 * 24.0
_JOURNAL_LOOKBACK = "24 hours ago"
_JOURNAL_TASK_LIMIT = 5

_MIN_BLOAT_TABLE_BYTES = 64 * 1024 * 1024
_MIN_BLOAT_DEAD_TUPLES = 1000
_BLOAT_WARN_PCT = 10.0
_BLOAT_CRIT_PCT = 20.0
_BLOAT_CRIT_DEAD_BYTES = 128 * 1024 * 1024
_MAX_VACUUM_TABLES_PER_DB = 3

_ACTION_COOLDOWN_HOURS = {
    "backup_catchup": 12.0,
    "pending_drain": 6.0,
    "vacuum_analyze": 24.0,
}

Severity = Literal["warning", "critical"]


def _now() -> datetime:
    return datetime.now(UTC)


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _hours_since(value: Any, *, now: datetime) -> float | None:
    dt = _coerce_datetime(value)
    if dt is None:
        return None
    return round((now - dt).total_seconds() / 3600, 2)


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _severity_rank(value: Severity | str) -> int:
    return 2 if value == "critical" else 1


def _status_from_severity(severity: Severity | None) -> str:
    if severity == "critical":
        return "critical"
    if severity == "warning":
        return "warning"
    return "ok"


def _mount_map() -> dict[str, dict[str, Any]]:
    return {
        str(item["mount_path"]): {
            "label": item.get("label"),
            "mount_path": item.get("mount_path"),
            "total_gb": item.get("total_gb"),
            "used_gb": item.get("used_gb"),
            "free_gb": item.get("free_gb"),
            "percent_used": item.get("percent_used"),
            "status": item.get("status"),
        }
        for item in get_disk_usages()
    }


def _collect_top_processes(limit: int = 5) -> list[dict[str, Any]]:
    procs = []
    try:
        processes = list(psutil.process_iter(["pid", "name", "username", "memory_info", "cmdline"]))
        for proc in processes:
            try:
                proc.cpu_percent(None)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        time.sleep(0.1)
        for proc in processes:
            try:
                info = proc.as_dict(attrs=["pid", "name", "username", "memory_info", "cmdline"])
                rss = int(getattr(info.get("memory_info"), "rss", 0) or 0)
                cpu = float(proc.cpu_percent(None))
                cmdline = info.get("cmdline") or []
                procs.append(
                    {
                        "pid": info.get("pid"),
                        "name": info.get("name") or "unknown",
                        "user": info.get("username") or "unknown",
                        "cpu_percent": round(cpu, 2),
                        "rss_mb": round(rss / (1024 * 1024), 1),
                        "cmd": " ".join(str(part) for part in cmdline[:6])[:180],
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        logger.exception("runtime_hygiene_top_processes_failed")
        return []

    return sorted(procs, key=lambda item: (item["cpu_percent"], item["rss_mb"]), reverse=True)[:limit]


def _collect_host_snapshot(*, include_top_processes: bool) -> dict[str, Any]:
    disks = _mount_map()
    root_disk = disks.get(_ROOT_MOUNT) or {
        "label": "Root",
        "mount_path": _ROOT_MOUNT,
        "total_gb": 0.0,
        "used_gb": 0.0,
        "free_gb": 0.0,
        "percent_used": 0.0,
        "status": "unknown",
    }
    memory = get_memory_usage()
    cpu = get_cpu_usage()
    summary = {
        "disk": root_disk,
        "disks": list(disks.values()),
        "memory": memory,
        "cpu": cpu,
    }
    if include_top_processes:
        summary["top_processes"] = _collect_top_processes()
    return summary


def _latest_run(workflow_name: str) -> dict[str, Any] | None:
    runs = maintenance_store.list_maintenance_runs(limit=1, workflow_name=workflow_name)
    return runs[0] if runs else None


def _run_started_within(workflow_name: str, *, hours: float, now: datetime) -> bool:
    latest = _latest_run(workflow_name)
    if latest is None:
        return False
    started_at = _coerce_datetime(latest.get("started_at"))
    return bool(started_at and now - started_at <= timedelta(hours=hours))


def _latest_runtime_hygiene_run() -> dict[str, Any] | None:
    return _latest_run(_WORKFLOW_NAME)


def _recent_action_succeeded(
    latest_run: dict[str, Any] | None,
    *,
    action_type: str,
    fingerprint: str,
    now: datetime,
) -> bool:
    if latest_run is None:
        return False
    started_at = _coerce_datetime(latest_run.get("started_at"))
    cooldown = _ACTION_COOLDOWN_HOURS.get(action_type)
    if started_at is None or cooldown is None or now - started_at > timedelta(hours=cooldown):
        return False
    summary = latest_run.get("summary") if isinstance(latest_run.get("summary"), dict) else {}
    actions = summary.get("actions_taken") if isinstance(summary, dict) else []
    if not isinstance(actions, list):
        return False
    return any(
        isinstance(action, dict)
        and action.get("type") == action_type
        and action.get("fingerprint") == fingerprint
        and action.get("status") == "completed"
        for action in actions
    )


def _backup_rows_by_source() -> dict[str, dict[str, Any]]:
    return {
        str(row["source_id"]): row
        for row in backup_store.get_backup_health_summary()
        if isinstance(row, dict) and row.get("source_id")
    }


def _backup_state(row: dict[str, Any] | None, *, now: datetime, source_type: str) -> dict[str, Any]:
    if row is None:
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

    backup_age = _hours_since(row.get("last_success_at"), now=now)
    restore_age = _hours_since(row.get("last_restore_tested_at"), now=now)
    drill_age = _hours_since(row.get("last_drill_at"), now=now)
    backup_status = row.get("last_backup_status")
    pending_upload_count = int(row.get("pending_upload_count") or 0)

    is_fresh = backup_age is not None and backup_age <= _BACKUP_FRESH_HOURS and backup_status in {
        "completed",
        "completed_pending_upload",
    }
    if source_type == "infrastructure":
        restore_ok = bool(row.get("last_drill_ok") is True and drill_age is not None and drill_age <= _INFRA_DRILL_STALE_HOURS)
    else:
        restore_ok = bool(
            row.get("last_restore_test_ok") is True
            and restore_age is not None
            and restore_age <= _RESTORE_TEST_STALE_HOURS
        )
    return {
        "status": "ok" if is_fresh else "stale",
        "source_type": source_type,
        "source_id": row.get("source_id"),
        "backup_age_hours": backup_age,
        "restore_age_hours": restore_age,
        "drill_age_hours": drill_age,
        "is_fresh": is_fresh,
        "restore_validation_ok": restore_ok,
        "pending_upload_count": pending_upload_count,
        "last_backup_status": backup_status,
        "last_success_at": row.get("last_success_at"),
        "last_restore_tested_at": row.get("last_restore_tested_at"),
        "last_restore_test_ok": row.get("last_restore_test_ok"),
        "last_drill_at": row.get("last_drill_at"),
        "last_drill_ok": row.get("last_drill_ok"),
        "last_drill_backup_id": row.get("last_drill_backup_id"),
    }


def _normalize_bloat_row(row: Any) -> dict[str, Any]:
    schemaname, relname, total_bytes, n_live_tup, n_dead_tup, last_autovacuum, last_vacuum = row
    schema = str(schemaname or "public")
    live = int(n_live_tup or 0)
    dead = int(n_dead_tup or 0)
    total = int(total_bytes or 0)
    total_tuples = live + dead
    dead_pct = round((dead / total_tuples) * 100, 2) if total_tuples else 0.0
    dead_bytes = int(total * (dead / total_tuples)) if total_tuples else 0
    severity: Severity | None = None
    if total >= _MIN_BLOAT_TABLE_BYTES and dead >= _MIN_BLOAT_DEAD_TUPLES and dead_pct >= _BLOAT_WARN_PCT:
        severity = "critical" if dead_pct >= _BLOAT_CRIT_PCT or dead_bytes >= _BLOAT_CRIT_DEAD_BYTES else "warning"
    return {
        "schema": schema,
        "table": str(relname),
        "table_ref": f"{schema}.{relname}",
        "total_bytes": total,
        "total_mb": round(total / (1024 * 1024), 1),
        "n_live_tup": live,
        "n_dead_tup": dead,
        "dead_pct": dead_pct,
        "dead_bytes": dead_bytes,
        "dead_mb": round(dead_bytes / (1024 * 1024), 1),
        "severity": severity,
        "last_autovacuum": _json_safe(last_autovacuum),
        "last_vacuum": _json_safe(last_vacuum),
    }


def _query_bloat_candidates(project_id: str) -> dict[str, Any]:
    db_url = get_db_url_for_project(project_id)
    if not db_url:
        return {
            "status": "unavailable",
            "reason": "db_url_missing",
            "project_id": project_id,
            "candidates": [],
        }

    query = """
        SELECT
            schemaname,
            relname,
            pg_total_relation_size(relid) AS total_bytes,
            n_live_tup,
            n_dead_tup,
            last_autovacuum,
            last_vacuum
        FROM pg_stat_user_tables
        ORDER BY pg_total_relation_size(relid) DESC, relname ASC
    """
    try:
        with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
    except Exception as exc:
        logger.warning("runtime_hygiene_bloat_query_failed", project_id=project_id, error=str(exc))
        return {
            "status": "unavailable",
            "reason": str(exc),
            "project_id": project_id,
            "candidates": [],
        }

    normalized = [_normalize_bloat_row(row) for row in rows]
    candidates = [row for row in normalized if row.get("severity")]
    severity = None
    for candidate in candidates:
        candidate_severity = candidate.get("severity")
        if candidate_severity and (severity is None or _severity_rank(candidate_severity) > _severity_rank(severity)):
            severity = candidate_severity

    return {
        "status": _status_from_severity(severity),
        "project_id": project_id,
        "db_url_available": True,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def _vacuum_analyze_table(project_id: str, schema_name: str, table_name: str) -> dict[str, Any]:
    db_url = get_db_url_for_project(project_id)
    if not db_url:
        return {"status": "failed", "error": "db_url_missing"}
    try:
        with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(
                sql.SQL("VACUUM (ANALYZE) {}.{};").format(
                    sql.Identifier(schema_name),
                    sql.Identifier(table_name),
                )
            )
        return {"status": "completed", "schema": schema_name, "table": table_name, "table_ref": f"{schema_name}.{table_name}"}
    except Exception as exc:
        logger.warning(
            "runtime_hygiene_vacuum_failed",
            project_id=project_id,
            table=f"{schema_name}.{table_name}",
            error=str(exc),
        )
        return {
            "status": "failed",
            "schema": schema_name,
            "table": table_name,
            "table_ref": f"{schema_name}.{table_name}",
            "error": str(exc),
        }


def _active_issue_task(project_id: str, issue_key: str) -> str | None:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT t.id
            FROM tasks t
            JOIN task_spirit ts ON ts.task_id = t.id
            WHERE t.project_id = %s
              AND t.status NOT IN ('completed', 'cancelled')
              AND ts.context -> %s ->> 'issue_key' = %s
            ORDER BY t.created_at ASC
            LIMIT 1
            """,
            (project_id, _RUNTIME_CTX_KEY, issue_key),
        )
        row = cur.fetchone()
    return str(row[0]) if row else None


def _issue_context(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        _RUNTIME_CTX_KEY: {
            "issue_key": issue["issue_key"],
            "scope": issue["scope"],
            "issue_type": issue["issue_type"],
            "fingerprint": issue["fingerprint"],
            "severity": issue["severity"],
            "project_id": issue["project_id"],
            "summary": issue["summary"],
            "evidence": _json_safe(issue["evidence"]),
            "updated_at": _now().isoformat(),
        }
    }


def _issue_description(issue: dict[str, Any]) -> str:
    evidence_text = json.dumps(_json_safe(issue["evidence"]), indent=2, sort_keys=True)
    return (
        "Runtime hygiene found an unresolved maintenance issue.\n\n"
        f"Scope: {issue['scope']}\n"
        f"Issue type: {issue['issue_type']}\n"
        f"Severity: {issue['severity']}\n"
        f"Fingerprint: {issue['fingerprint']}\n\n"
        f"Summary: {issue['summary']}\n\n"
        "Evidence:\n"
        f"```json\n{evidence_text[:6000]}\n```\n"
    )


def _task_priority(issue: dict[str, Any]) -> int:
    return 1 if issue["severity"] == "critical" else 2


def _task_type(issue: dict[str, Any]) -> str:
    return "bug" if issue["issue_type"] in {"db_access", "db_bloat", "backup", "resource"} else "task"


def _task_subtask_type(issue: dict[str, Any]) -> str:
    return "database" if issue["issue_type"] in {"db_access", "db_bloat"} else "devops"


def _create_or_refresh_issue_task(issue: dict[str, Any]) -> tuple[str, bool]:
    project_id = str(issue["project_id"])
    issue_key = str(issue["issue_key"])
    existing = _active_issue_task(project_id, issue_key)
    description = _issue_description(issue)
    context = _issue_context(issue)
    labels = ["runtime-hygiene", str(issue["scope"]), str(issue["issue_type"]), str(issue["severity"])]
    if existing:
        task_store.update_task(existing, description=description, priority=_task_priority(issue), labels=labels)
        current_spirit = get_task_spirit(existing) or {}
        merged_context = current_spirit.get("context") if isinstance(current_spirit, dict) else None
        if not isinstance(merged_context, dict):
            merged_context = {}
        merged_context.update(context)
        update_task_spirit(existing, context=merged_context)
        return existing, False

    created = task_store.create_task(
        project_id=project_id,
        title=str(issue["title"]),
        description=description,
        priority=_task_priority(issue),
        task_type=_task_type(issue),
        complexity="STANDARD",
        execution_mode="autonomous",
        autonomous=True,
        labels=labels,
    )
    task_id = str(created["id"])
    create_task_spirit(task_id=task_id, done_when=_DONE_WHEN, context=context, complexity="STANDARD")
    approve_plan(task_id, approved_by="runtime-hygiene")
    create_single_subtask_with_steps(
        task_id=task_id,
        subtask_id="1.1",
        phase="backend" if _task_subtask_type(issue) == "database" else "ops",
        description=f"Resolve runtime hygiene finding: {issue['summary']}",
        subtask_type=_task_subtask_type(issue),
    )
    return task_id, True


def _issue(
    *,
    scope: str,
    issue_type: str,
    fingerprint: str,
    severity: Severity,
    summary: str,
    evidence: dict[str, Any],
    project_id: str,
) -> dict[str, Any]:
    issue_key = f"runtime-hygiene:{scope}:{issue_type}:{fingerprint}"
    return {
        "scope": scope,
        "issue_type": issue_type,
        "fingerprint": fingerprint,
        "issue_key": issue_key,
        "severity": severity,
        "summary": summary,
        "evidence": evidence,
        "project_id": project_id,
        "title": f"Handle runtime hygiene: {summary[:110]}",
    }


def _project_issue(project_id: str, issue_type: str, fingerprint: str, severity: Severity, summary: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return _issue(
        scope=project_id,
        issue_type=issue_type,
        fingerprint=fingerprint,
        severity=severity,
        summary=summary,
        evidence=evidence,
        project_id=project_id,
    )


def _host_issue(issue_type: str, fingerprint: str, severity: Severity, summary: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return _issue(
        scope=_HOST_SCOPE,
        issue_type=issue_type,
        fingerprint=fingerprint,
        severity=severity,
        summary=summary,
        evidence=evidence,
        project_id="summitflow",
    )


def _journal_findings(project_id: str) -> dict[str, Any]:
    pattern = _JOURNAL_PATTERNS[project_id]
    monitor = SystemdMonitor(unit_pattern=pattern, since=_JOURNAL_LOOKBACK)
    raw_errors = monitor.parse_journal()
    unique: dict[str, Any] = {}
    for error in raw_errors:
        unique.setdefault(error.error_hash, error)
    return {
        "status": "issues" if unique else "ok",
        "pattern": pattern,
        "issue_count": len(unique),
        "created_task_ids": [],
        "errors": [
            {
                "unit": error.unit,
                "priority": error.priority,
                "error_hash": error.error_hash,
                "timestamp": error.timestamp.isoformat(),
                "message": error.message[:300],
            }
            for error in list(unique.values())[:_JOURNAL_TASK_LIMIT]
        ],
    }


def _record_action(actions: list[dict[str, Any]], *, action_type: str, scope: str, fingerprint: str, status: str, detail: str, **extra: Any) -> None:
    action = {
        "type": action_type,
        "scope": scope,
        "fingerprint": fingerprint,
        "status": status,
        "detail": detail,
    }
    action.update(_json_safe(extra))
    actions.append(action)


def _normalize_action_status(value: Any) -> str:
    raw = str(value or "").lower()
    if raw in {"success", "completed"}:
        return "completed"
    if raw in {"completed_pending_upload", "partial"}:
        return "partial"
    if raw in {"idle", "skipped", "disabled"}:
        return "skipped"
    if raw in {"failed", "error"}:
        return "failed"
    return raw or "unknown"


def _ensure_backup_fresh(
    *,
    project_id: str,
    source_id: str,
    backup_rows: dict[str, dict[str, Any]],
    latest_runtime_hygiene: dict[str, Any] | None,
    actions_taken: list[dict[str, Any]],
    now: datetime,
) -> dict[str, Any]:
    row = backup_rows.get(source_id)
    state = _backup_state(row, now=now, source_type="project")
    fingerprint = f"backup:{source_id}"

    if state["pending_upload_count"] > 0 and state["is_fresh"]:
        if not _recent_action_succeeded(latest_runtime_hygiene, action_type="pending_drain", fingerprint=fingerprint, now=now):
            drain_result = drain_pending_backups(dry_run=False)
            _record_action(
                actions_taken,
                action_type="pending_drain",
                scope=project_id,
                fingerprint=fingerprint,
                status=_normalize_action_status(drain_result.get("status")),
                detail=str(drain_result.get("message") or "pending drain run"),
                result=drain_result,
            )
        backup_rows.update(_backup_rows_by_source())
        state = _backup_state(backup_rows.get(source_id), now=now, source_type="project")

    if state["is_fresh"] and state["last_backup_status"] == "completed":
        return state

    if _recent_action_succeeded(latest_runtime_hygiene, action_type="backup_catchup", fingerprint=fingerprint, now=now):
        return state

    backup_result = create_backup(
        project_id=project_id,
        source_id=source_id,
        backup_type="manual",
        note="Runtime hygiene catch-up backup",
    )
    _record_action(
        actions_taken,
        action_type="backup_catchup",
        scope=project_id,
        fingerprint=fingerprint,
        status=_normalize_action_status(backup_result.get("status")),
        detail=f"Triggered catch-up backup for {source_id}",
        result=backup_result,
    )
    backup_rows.update(_backup_rows_by_source())
    return _backup_state(backup_rows.get(source_id), now=now, source_type="project")


def _project_target(
    project_id: str,
    *,
    backup_rows: dict[str, dict[str, Any]],
    latest_runtime_hygiene: dict[str, Any] | None,
    now: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str], list[str]]:
    created_task_ids: list[str] = []
    reused_task_ids: list[str] = []
    actions_taken: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    source_id = _TARGET_BACKUP_SOURCES[project_id]
    backup_state = _backup_state(backup_rows.get(source_id), now=now, source_type="project")
    journal = _journal_findings(project_id)
    if int(journal.get("issue_count") or 0) > 0:
        issues.append(
            _project_issue(
                project_id,
                "journal",
                "journal-errors",
                "warning",
                f"Investigate recent {project_id} runtime journal errors",
                {
                    "journal": {
                        "pattern": journal.get("pattern"),
                        "issue_count": journal.get("issue_count"),
                        "errors": list(journal.get("errors") or []),
                    }
                },
            )
        )

    if not backup_state["is_fresh"] or backup_state["pending_upload_count"] > 0:
        backup_state = _ensure_backup_fresh(
            project_id=project_id,
            source_id=source_id,
            backup_rows=backup_rows,
            latest_runtime_hygiene=latest_runtime_hygiene,
            actions_taken=actions_taken,
            now=now,
        )

    if not backup_state["is_fresh"]:
        issues.append(
            _project_issue(
                project_id,
                "backup",
                source_id,
                "critical",
                f"{project_id} backup protection is stale or unavailable",
                {"backup": backup_state},
            )
        )
    elif backup_state["pending_upload_count"] > 0:
        issues.append(
            _project_issue(
                project_id,
                "backup",
                source_id,
                "warning",
                f"{project_id} backup is still pending upload after drain attempt",
                {"backup": backup_state},
            )
        )

    if not backup_state["restore_validation_ok"]:
        issues.append(
            _project_issue(
                project_id,
                "restore_validation",
                source_id,
                "warning",
                f"{project_id} restore validation is stale or failing",
                {"backup": backup_state},
            )
        )

    bloat = _query_bloat_candidates(project_id)
    vacuumed: list[dict[str, Any]] = []
    skipped_candidates: list[dict[str, Any]] = []
    if bloat.get("status") != "unavailable":
        candidates = list(bloat.get("candidates") or [])
        actionable = sorted(
            candidates,
            key=lambda item: (item.get("dead_bytes") or 0, item.get("dead_pct") or 0.0),
            reverse=True,
        )
        if actionable and backup_state["is_fresh"] and backup_state["last_backup_status"] == "completed":
            for candidate in actionable[:_MAX_VACUUM_TABLES_PER_DB]:
                fingerprint = f"vacuum:{project_id}:{candidate['table_ref']}"
                if _recent_action_succeeded(latest_runtime_hygiene, action_type="vacuum_analyze", fingerprint=fingerprint, now=now):
                    skipped_candidates.append({**candidate, "skip_reason": "recent_vacuum"})
                    continue
                vacuum_result = _vacuum_analyze_table(project_id, str(candidate["schema"]), str(candidate["table"]))
                vacuumed.append({**candidate, **vacuum_result})
                _record_action(
                    actions_taken,
                    action_type="vacuum_analyze",
                    scope=project_id,
                    fingerprint=fingerprint,
                    status=_normalize_action_status(vacuum_result.get("status")),
                    detail=f"VACUUM ANALYZE {candidate['schema']}.{candidate['table']}",
                    result=vacuum_result,
                )
            if vacuumed:
                bloat = _query_bloat_candidates(project_id)
        elif actionable:
            skipped_candidates.extend(
                [{**candidate, "skip_reason": "backup_prerequisite_not_satisfied"} for candidate in actionable]
            )

        if actionable and not vacuumed:
            refreshed_bloat = _query_bloat_candidates(project_id)
            if refreshed_bloat.get("status") != "unavailable":
                bloat = refreshed_bloat
        remaining_candidates = list(bloat.get("candidates") or [])
        if skipped_candidates:
            bloat["skipped_candidates"] = skipped_candidates
        if vacuumed:
            bloat["vacuumed"] = vacuumed
        if remaining_candidates:
            for candidate in remaining_candidates:
                severity = candidate.get("severity") or "warning"
                issues.append(
                    _project_issue(
                        project_id,
                        "db_bloat",
                        str(candidate["table_ref"]),
                        severity if severity in {"warning", "critical"} else "warning",
                        f"{project_id} table {candidate['table_ref']} still shows actionable DB bloat",
                        {"bloat": candidate, "backup": backup_state},
                    )
                )
    else:
        issues.append(
            _project_issue(
                project_id,
                "db_access",
                "db-access",
                "warning",
                f"{project_id} DB bloat check is unavailable",
                {"bloat": bloat},
            )
        )

    for issue in issues:
        if issue.get("managed_externally"):
            existing_task_id = issue.get("task_id")
            if existing_task_id:
                reused_task_ids.append(str(existing_task_id))
            continue
        task_id, created = _create_or_refresh_issue_task(issue)
        issue["task_id"] = task_id
        if created:
            created_task_ids.append(task_id)
        else:
            reused_task_ids.append(task_id)

    severity: Severity | None = None
    journal_task_ids = [
        str(issue.get("task_id"))
        for issue in issues
        if issue.get("issue_type") == "journal" and issue.get("task_id")
    ]
    journal["created_task_ids"] = journal_task_ids
    for issue in issues:
        issue_severity = issue["severity"]
        if severity is None or _severity_rank(issue_severity) > _severity_rank(severity):
            severity = issue_severity

    target_summary = {
        "project_id": project_id,
        "status": _status_from_severity(severity),
        "backup": backup_state,
        "journal": journal,
        "bloat": bloat,
        "actions_taken": actions_taken,
        "unresolved_issue_count": len(issues),
        "created_task_ids": created_task_ids,
        "reused_task_ids": reused_task_ids,
    }
    return target_summary, issues, created_task_ids, reused_task_ids


def _infrastructure_protection(
    *,
    backup_rows: dict[str, dict[str, Any]],
    latest_runtime_hygiene: dict[str, Any] | None,
    actions_taken: list[dict[str, Any]],
    now: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str], list[str]]:
    created_task_ids: list[str] = []
    reused_task_ids: list[str] = []
    issues: list[dict[str, Any]] = []

    source_id = _INFRA_SOURCE_ID
    row = backup_rows.get(source_id)
    state = _backup_state(row, now=now, source_type="infrastructure")
    fingerprint = f"backup:{source_id}"
    if not state["is_fresh"] and not _recent_action_succeeded(
        latest_runtime_hygiene,
        action_type="backup_catchup",
        fingerprint=fingerprint,
        now=now,
    ):
        backup_result = create_backup(
            project_id="infrastructure",
            source_id=source_id,
            backup_type="manual",
            note="Runtime hygiene catch-up infrastructure backup",
        )
        _record_action(
            actions_taken,
            action_type="backup_catchup",
            scope=_HOST_SCOPE,
            fingerprint=fingerprint,
            status=_normalize_action_status(backup_result.get("status")),
            detail="Triggered infrastructure catch-up backup",
            result=backup_result,
        )
        backup_rows.update(_backup_rows_by_source())
        state = _backup_state(backup_rows.get(source_id), now=now, source_type="infrastructure")

    if not state["is_fresh"]:
        issues.append(
            _host_issue(
                "backup",
                source_id,
                "critical",
                "Infrastructure backup protection is stale or unavailable",
                {"backup": state},
            )
        )
    if not state["restore_validation_ok"]:
        issues.append(
            _host_issue(
                "restore_validation",
                source_id,
                "warning",
                "Infrastructure restore drill is stale or failing",
                {"backup": state},
            )
        )

    for issue in issues:
        task_id, created = _create_or_refresh_issue_task(issue)
        issue["task_id"] = task_id
        if created:
            created_task_ids.append(task_id)
        else:
            reused_task_ids.append(task_id)

    severity: Severity | None = None
    for issue in issues:
        issue_severity = issue["severity"]
        if severity is None or _severity_rank(issue_severity) > _severity_rank(severity):
            severity = issue_severity

    return {
        "status": _status_from_severity(severity),
        "backup": state,
    }, issues, created_task_ids, reused_task_ids


def _host_pressure(
    *,
    latest_runtime_hygiene: dict[str, Any] | None,
    now: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
    host = _collect_host_snapshot(include_top_processes=False)
    actions_taken: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    created_task_ids: list[str] = []
    reused_task_ids: list[str] = []

    root_disk = host["disk"]
    root_pressure = (
        float(root_disk.get("percent_used") or 0.0) >= _DISK_WARN_PERCENT
        or float(root_disk.get("free_gb") or 0.0) <= _DISK_REMEDIATE_FREE_GB
    )
    if root_pressure:
        # When disk pressure is still present, rerun the bounded cleanup on each hygiene pass.
        # The routine should not skip cleanup just because a previous runtime_hygiene run happened recently.
        if _run_started_within("daily_maintenance", hours=6.0, now=now):
            _record_action(
                actions_taken,
                action_type="host_cleanup",
                scope=_HOST_SCOPE,
                fingerprint="host:root",
                status="skipped",
                detail="Skipped host cleanup because daily_maintenance ran within the last 6 hours",
            )
        else:
            cleanup_result = cleanup_host_artifacts()
            _record_action(
                actions_taken,
                action_type="host_cleanup",
                scope=_HOST_SCOPE,
                fingerprint="host:root",
                status=_normalize_action_status(cleanup_result.get("status")),
                detail="Ran host artifact cleanup",
                result=cleanup_result,
            )
            host = _collect_host_snapshot(include_top_processes=False)
            host["cleanup"] = cleanup_result

    needs_top = False
    root_disk = host["disk"]
    disk_percent = float(root_disk.get("percent_used") or 0.0)
    root_free_gb = float(root_disk.get("free_gb") or 0.0)
    if disk_percent >= _DISK_WARN_PERCENT or root_free_gb <= _DISK_REMEDIATE_FREE_GB:
        severity: Severity = "critical" if disk_percent >= _DISK_CRIT_PERCENT or root_free_gb <= _DISK_CRIT_FREE_GB else "warning"
        issues.append(
            _host_issue(
                "resource",
                "root-disk",
                severity,
                f"Root disk pressure remains at {root_disk.get('percent_used')}% used with {root_disk.get('free_gb')} GiB free",
                {"disk": root_disk, "cleanup": host.get("cleanup")},
            )
        )
    memory = host["memory"]
    if float(memory.get("percent_used") or 0.0) >= _MEMORY_WARN_PERCENT:
        needs_top = True
        severity = "critical" if float(memory.get("percent_used") or 0.0) >= _MEMORY_CRIT_PERCENT else "warning"
        issues.append(
            _host_issue(
                "resource",
                "memory",
                severity,
                f"Host memory pressure is {memory.get('percent_used')}% used",
                {"memory": memory},
            )
        )
    cpu = host["cpu"]
    if float(cpu.get("percent_used") or 0.0) >= _CPU_WARN_PERCENT:
        needs_top = True
        severity = "critical" if float(cpu.get("percent_used") or 0.0) >= _CPU_CRIT_PERCENT else "warning"
        issues.append(
            _host_issue(
                "resource",
                "cpu",
                severity,
                f"Host CPU pressure is {cpu.get('percent_used')}% used",
                {"cpu": cpu},
            )
        )

    if needs_top:
        host["top_processes"] = _collect_top_processes()
        for issue in issues:
            if issue["fingerprint"] in {"memory", "cpu"}:
                issue["evidence"]["top_processes"] = host["top_processes"]

    for issue in issues:
        task_id, created = _create_or_refresh_issue_task(issue)
        issue["task_id"] = task_id
        if created:
            created_task_ids.append(task_id)
        else:
            reused_task_ids.append(task_id)

    return host, actions_taken, issues, created_task_ids, reused_task_ids


def run_runtime_hygiene() -> dict[str, Any]:
    """Run one daily runtime hygiene audit and record the summary."""
    started_at = _now()
    latest_runtime_hygiene = _latest_runtime_hygiene_run()
    try:
        backup_rows = _backup_rows_by_source()
        host, host_actions, host_issues, host_created, host_reused = _host_pressure(
            latest_runtime_hygiene=latest_runtime_hygiene,
            now=started_at,
        )
        infra_summary, infra_issues, infra_created, infra_reused = _infrastructure_protection(
            backup_rows=backup_rows,
            latest_runtime_hygiene=latest_runtime_hygiene,
            actions_taken=host_actions,
            now=started_at,
        )

        targets: dict[str, Any] = {}
        all_issues: list[dict[str, Any]] = [*host_issues, *infra_issues]
        created_task_ids = [*host_created, *infra_created]
        reused_task_ids = [*host_reused, *infra_reused]
        actions_taken = list(host_actions)

        for project_id in _PROJECTS:
            target_summary, target_issues, created_ids, reused_ids = _project_target(
                project_id,
                backup_rows=backup_rows,
                latest_runtime_hygiene=latest_runtime_hygiene,
                now=started_at,
            )
            targets[project_id] = target_summary
            all_issues.extend(target_issues)
            created_task_ids.extend(created_ids)
            reused_task_ids.extend(reused_ids)
            actions_taken.extend(target_summary.get("actions_taken") or [])

        unresolved = [
            {
                "scope": issue["scope"],
                "issue_type": issue["issue_type"],
                "severity": issue["severity"],
                "summary": issue["summary"],
                "fingerprint": issue["fingerprint"],
                "task_id": issue.get("task_id"),
            }
            for issue in all_issues
        ]
        skipped_reasons = [
            action["detail"]
            for action in actions_taken
            if action.get("status") == "skipped"
        ]

        result = {
            "status": "partial" if unresolved else "success",
            "host": host,
            "infrastructure": infra_summary,
            "targets": targets,
            "actions_taken": actions_taken,
            "unresolved_issues": unresolved,
            "created_task_ids": sorted(set(created_task_ids)),
            "reused_task_ids": sorted(set(reused_task_ids)),
            "skipped_reasons": skipped_reasons,
        }
        maintenance_store.record_maintenance_run(
            _WORKFLOW_NAME,
            result["status"],
            started_at=started_at,
            finished_at=_now(),
            rows_cleaned=len(result["created_task_ids"]),
            summary=_json_safe(result),
        )
        return result
    except Exception as exc:
        logger.exception("runtime_hygiene_failed")
        maintenance_store.record_maintenance_run(
            _WORKFLOW_NAME,
            "failed",
            started_at=started_at,
            finished_at=_now(),
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
        raise


__all__ = ["run_runtime_hygiene"]
