"""Runtime hygiene follow-up task helpers."""

from __future__ import annotations

import json
from typing import Any

from .runtime_hygiene_common import (
    DONE_WHEN,
    HOST_SCOPE,
    RUNTIME_CTX_KEY,
    Severity,
    json_safe,
    now_utc,
)


def active_issue_task(project_id: str, issue_key: str, deps: Any) -> str | None:
    with deps.get_cursor() as cur:
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
            (project_id, RUNTIME_CTX_KEY, issue_key),
        )
        row = cur.fetchone()
    return str(row[0]) if row else None


def create_or_refresh_issue_task(issue: dict[str, Any], deps: Any) -> tuple[str, bool]:
    project_id = str(issue["project_id"])
    issue_key = str(issue["issue_key"])
    existing = active_issue_task(project_id, issue_key, deps)
    description = _issue_description(issue)
    context = _issue_context(issue)
    labels = ["runtime-hygiene", str(issue["scope"]), str(issue["issue_type"]), str(issue["severity"])]
    if existing:
        _refresh_existing_issue_task(existing, issue, description, context, labels, deps)
        return existing, False
    return _create_issue_task(project_id, issue, description, context, labels, deps), True


def issue(
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


def project_issue(
    project_id: str,
    issue_type: str,
    fingerprint: str,
    severity: Severity,
    summary: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return issue(
        scope=project_id,
        issue_type=issue_type,
        fingerprint=fingerprint,
        severity=severity,
        summary=summary,
        evidence=evidence,
        project_id=project_id,
    )


def host_issue(
    issue_type: str,
    fingerprint: str,
    severity: Severity,
    summary: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return issue(
        scope=HOST_SCOPE,
        issue_type=issue_type,
        fingerprint=fingerprint,
        severity=severity,
        summary=summary,
        evidence=evidence,
        project_id="summitflow",
    )


def persist_issues(
    issues: list[dict[str, Any]],
    deps: Any,
) -> tuple[list[str], list[str]]:
    created_task_ids: list[str] = []
    reused_task_ids: list[str] = []
    for item in issues:
        if item.get("managed_externally"):
            _reuse_external_task(item, reused_task_ids)
            continue
        task_id, created = deps._create_or_refresh_issue_task(item)
        item["task_id"] = task_id
        created_task_ids.append(task_id) if created else reused_task_ids.append(task_id)
    return created_task_ids, reused_task_ids


def highest_severity(issues: list[dict[str, Any]], deps: Any) -> Severity | None:
    severity: Severity | None = None
    for item in issues:
        issue_severity = item["severity"]
        if severity is None or deps._severity_rank(issue_severity) > deps._severity_rank(severity):
            severity = issue_severity
    return severity


def unresolved_issue_summary(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "scope": item["scope"],
            "issue_type": item["issue_type"],
            "severity": item["severity"],
            "summary": item["summary"],
            "fingerprint": item["fingerprint"],
            "task_id": item.get("task_id"),
        }
        for item in issues
    ]


def _issue_context(issue_data: dict[str, Any]) -> dict[str, Any]:
    return {
        RUNTIME_CTX_KEY: {
            "issue_key": issue_data["issue_key"],
            "scope": issue_data["scope"],
            "issue_type": issue_data["issue_type"],
            "fingerprint": issue_data["fingerprint"],
            "severity": issue_data["severity"],
            "project_id": issue_data["project_id"],
            "summary": issue_data["summary"],
            "evidence": json_safe(issue_data["evidence"]),
            "updated_at": now_utc().isoformat(),
        }
    }


def _issue_description(issue_data: dict[str, Any]) -> str:
    evidence_text = json.dumps(json_safe(issue_data["evidence"]), indent=2, sort_keys=True)
    return (
        "Runtime hygiene found an unresolved maintenance issue.\n\n"
        f"Scope: {issue_data['scope']}\n"
        f"Issue type: {issue_data['issue_type']}\n"
        f"Severity: {issue_data['severity']}\n"
        f"Fingerprint: {issue_data['fingerprint']}\n\n"
        f"Summary: {issue_data['summary']}\n\n"
        "Evidence:\n"
        f"```json\n{evidence_text[:6000]}\n```\n"
    )


def _refresh_existing_issue_task(
    task_id: str,
    issue_data: dict[str, Any],
    description: str,
    context: dict[str, Any],
    labels: list[str],
    deps: Any,
) -> None:
    deps.task_store.update_task(task_id, description=description, priority=_task_priority(issue_data), labels=labels)
    current_spirit = deps.get_task_spirit(task_id) or {}
    merged_context = current_spirit.get("context") if isinstance(current_spirit, dict) else None
    if not isinstance(merged_context, dict):
        merged_context = {}
    merged_context.update(context)
    deps.update_task_spirit(task_id, context=merged_context)


def _create_issue_task(
    project_id: str,
    issue_data: dict[str, Any],
    description: str,
    context: dict[str, Any],
    labels: list[str],
    deps: Any,
) -> str:
    created = deps.task_store.create_task(
        project_id=project_id,
        title=str(issue_data["title"]),
        description=description,
        priority=_task_priority(issue_data),
        task_type=_task_type(issue_data),
        complexity="STANDARD",
        execution_mode="autonomous",
        labels=labels,
    )
    task_id = str(created["id"])
    deps.create_task_spirit(task_id=task_id, done_when=DONE_WHEN, context=context, complexity="STANDARD")
    deps.approve_plan(task_id, approved_by="runtime-hygiene")
    _create_resolution_subtask(task_id, issue_data, deps)
    return task_id


def _create_resolution_subtask(task_id: str, issue_data: dict[str, Any], deps: Any) -> None:
    subtask_type = _task_subtask_type(issue_data)
    deps.create_single_subtask_with_steps(
        task_id=task_id,
        subtask_id="1.1",
        phase="backend" if subtask_type == "database" else "ops",
        description=f"Resolve runtime hygiene finding: {issue_data['summary']}",
        subtask_type=subtask_type,
    )


def _reuse_external_task(issue_data: dict[str, Any], reused_task_ids: list[str]) -> None:
    existing_task_id = issue_data.get("task_id")
    if existing_task_id:
        reused_task_ids.append(str(existing_task_id))


def _task_priority(issue_data: dict[str, Any]) -> int:
    return 1 if issue_data["severity"] == "critical" else 2


def _task_type(issue_data: dict[str, Any]) -> str:
    return "bug" if issue_data["issue_type"] in {"db_access", "db_bloat", "backup", "resource"} else "task"


def _task_subtask_type(issue_data: dict[str, Any]) -> str:
    return "database" if issue_data["issue_type"] in {"db_access", "db_bloat"} else "devops"
