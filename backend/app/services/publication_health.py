"""Read-only retained publication observations, independent of local completion."""
from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from app.storage.backups.queries import get_latest_backup
from app.storage.projects import get_project_root_path
from app.storage.tasks.publication_repair import finding_actionable, get_repair_task, record_finding

_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_REASON = re.compile(r"[a-z][a-z0-9_]*")
_DEFERRED = {"outside_publication_window", "outside_nightly_window", "repository_changed", "publication_busy",
             "source_busy", "remote_ci_pending", "repository_busy", "push_timeout", "transport_unavailable",
             "remote_transport_unavailable", "remote_authentication_unavailable", "remote_rate_limited",
             "remote_api_unavailable", "remote_ci_unavailable", "remote_publication_unavailable",
             "heavy_work_admission_unavailable"}
# Retain legacy reason codes so historical observations keep their meaning.
_SETUP_FAILURES = {"no_existing_upstream", "unsafe_remote_route", "incorrect_upstream_route",
                   "repository_archived", "remote_repository_archived", "ambiguous_upstream_route",
                   "ambiguous_remote_route", "mirror_remote", "jj_explicit_remote_required",
                   "jj_default_bookmark_required", "repository_root_mismatch", "not_git_repository",
                   "not_project_directory"}


def classify_observation(result: dict[str, Any]) -> dict[str, Any]:
    """Keep only safe structured metadata, not scanner/transport output or credential URLs."""
    head = result.get("head") or result.get("sha")
    head = head if isinstance(head, str) and _SHA.fullmatch(head) else None
    ci_value = result.get("ci")
    ci: dict[str, Any] = ci_value if isinstance(ci_value, dict) else {}
    ci_state = str(ci.get("state") or "unknown")
    status = str(result.get("status") or "unknown").lower()
    reason = str(result.get("reason") or "unknown")
    reason = reason if _REASON.fullmatch(reason) else "publication_needs_investigation"
    security_value = result.get("security")
    security: dict[str, Any] = security_value if isinstance(security_value, dict) else {}
    acceptance_value = result.get("acceptance")
    acceptance: dict[str, Any] = acceptance_value if isinstance(acceptance_value, dict) else {}
    pr_value = ci.get("pr_checks")
    pr_checks: dict[str, Any] = pr_value if isinstance(pr_value, dict) else {}
    observed_at = result.get("observed_at")
    try:
        timestamp = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
        observed_at = timestamp.astimezone(UTC).isoformat() if timestamp.tzinfo else None
    except (TypeError, ValueError):
        observed_at = None
    if ci_state == "failed" or security.get("state") in {"failed", "blocked"}:
        state = "blocked"
        reason = "remote_ci_failed" if ci_state == "failed" else "security_findings_open"
    elif reason in _SETUP_FAILURES or (status in {"failed", "blocked", "failure"} and reason not in _DEFERRED):
        state = "blocked"
    elif (head and observed_at and result.get("publication_complete") is True and ci_state in {"success", "not_applicable"}
          and ci.get("sha") and ci.get("sha") in {head, result.get("merge_sha")}
          and (ci.get("sha") == head or (pr_checks.get("state") in (
              {"success", "not_applicable"} if ci_state == "not_applicable" else {"success"}) and pr_checks.get("sha") == head))
          and security.get("state") == "success" and security.get("sha") == head
          and acceptance.get("source_commit") == head
          and ((acceptance.get("state") in {"success", "reused"} and acceptance.get("acceptance_id"))
               or (acceptance.get("state") == "not_required" and result.get("publication_mode") == "mirror"))):
        state = "verified" if ci_state == "success" else "published"
        if state == "published":
            reason = "published_without_ci"
    elif status in {"pending", "queued"} or reason in _DEFERRED:
        state = "pending"
    else:
        state = "unknown"
    return {"state": state, "reason": reason, "source_commit": head, "observed_at": observed_at,
            "ci_state": ci_state if ci_state in {"success", "failed", "pending", "not_applicable"} else "unknown"}


def record_publication_observation(project_id: str, result: dict[str, Any]) -> str | None:
    observation = classify_observation(result)
    if observation["state"] == "published":
        # A CI-less upload of an exactly accepted source proves only that local
        # acceptance now passes for a source including the failed one (the
        # stored ancestry proof). It never resolves CI, security or CodeQL.
        return record_finding(project_id, "publication", observation, resolved=True,
                              resolution_reasons=frozenset({"local_acceptance_failed"}))
    if observation["state"] not in {"blocked", "verified"}:
        return None
    # Outgoing secret verification and remote CodeQL findings are distinct.
    # A green publication may resolve the former, never independent CodeQL alerts.
    if observation["reason"] == "security_findings_open":
        return record_finding(project_id, "outgoing_security", observation, resolved=False)
    task_id = record_finding(project_id, "publication", observation, resolved=observation["state"] == "verified")
    if observation["state"] == "verified":
        record_finding(project_id, "outgoing_security", observation, resolved=True)
        # This proves CI now exists AND passes for the accepted source. Resolve
        # only the known missing-CI setup cause, never arbitrary CI policy or
        # independent CodeQL findings. Storage still requires failed-source
        # inclusion, observation ordering, and an exact-category CAS.
        record_finding(project_id, "cloud_ci", observation, resolved=True,
                       resolution_reasons=frozenset({"cloud_ci_missing"}))
    return task_id


def get_project_publication_health(project_id: str, *, now: datetime | None = None,
                                   connection: psycopg.Connection | None = None) -> dict[str, Any]:
    repair = get_repair_task(project_id, connection=connection)
    record = get_latest_backup(project_id=project_id, verification_key="publish_before_backup", connection=connection)
    verification = (record or {}).get("verification_json") or {}
    result = verification.get("publish_before_backup") or verification.get("publication") or {}
    evidence_path = None
    root = get_project_root_path(project_id)
    if root:
        from app.tasks.backup_manual_publish import latest_publication_receipt

        retained = latest_publication_receipt(Path(root), project_id)
        if retained:
            path, receipt = retained
            result = {**(receipt.get("observation") or {}), "observed_at": receipt.get("observed_at")}
            evidence_path = str(path)
    observation = classify_observation(result)
    if not observation["observed_at"] and observation["state"] == "verified":
        observation.update(state="unknown", reason="publication_observation_time_missing")
    findings = ((repair or {}).get("verification_result") or {}).get("publication_repair") or {}
    unresolved = sorted(key for key, finding in findings.items()
                        if isinstance(finding, dict) and finding_actionable(finding))
    if unresolved:
        observation.update(state="blocked", reason="actionable_repair_findings")
    return {"project_id": project_id, **observation, "repair_task_id": (repair or {}).get("id"),
            "unresolved_categories": unresolved, "findings": findings,
            "evidence": evidence_path, "backup_id": None if evidence_path else (record or {}).get("id")}


def format_publication_health(health: dict[str, Any]) -> str:
    return (f"Manual publication: {health['state']}; source={str(health.get('source_commit') or 'unknown')[:12]}; "
            f"observed={health.get('observed_at') or 'unknown'}; CI={health.get('ci_state', 'unknown')}; "
            f"reason={health.get('reason', 'unknown')}; repair={health.get('repair_task_id') or 'none'}")
