"""Truthful nightly health from existing backup publication receipts and repair tasks.

Publication pending is normal local-first development. Only retained actionable
defects block completion; a successful push alone is never a healthy CI result.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import psycopg

from app.storage.backups.queries import get_latest_backup
from app.storage.tasks.publication_repair import get_repair_task, record_finding

_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_REASON = re.compile(r"[a-z][a-z0-9_]*")
_DEFERRED = {"outside_publication_window", "outside_nightly_window", "repository_changed", "publication_busy",
             "source_busy", "remote_ci_pending", "repository_busy", "push_timeout", "transport_unavailable",
             "remote_transport_unavailable", "remote_authentication_unavailable", "remote_rate_limited",
             "remote_api_unavailable", "remote_ci_unavailable", "remote_publication_unavailable"}
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
    elif (head and observed_at and result.get("publication_complete") is True and ci_state == "success"
          and ci.get("sha") and ci.get("sha") in {head, result.get("merge_sha")}
          and (ci.get("sha") == head or (pr_checks.get("state") == "success" and pr_checks.get("sha") == head))
          and security.get("state") == "success" and security.get("sha") == head
          and acceptance.get("state") in {"success", "reused"}
          and acceptance.get("source_commit") == head and acceptance.get("acceptance_id")):
        state = "verified"
    elif status in {"pending", "queued"} or reason in _DEFERRED:
        state = "pending"
    else:
        state = "unknown"
    return {"state": state, "reason": reason, "source_commit": head, "observed_at": observed_at,
            "ci_state": ci_state if ci_state in {"success", "failed", "pending", "not_applicable"} else "unknown"}


def record_publication_observation(project_id: str, result: dict[str, Any]) -> str | None:
    observation = classify_observation(result)
    if observation["state"] not in {"blocked", "verified"}:
        return None
    # Outgoing secret verification and remote CodeQL findings are distinct.
    # A green publication may resolve the former, never independent CodeQL alerts.
    if observation["reason"] == "security_findings_open":
        return record_finding(project_id, "outgoing_security", observation, resolved=False)
    task_id = record_finding(project_id, "publication", observation, resolved=observation["state"] == "verified")
    if observation["state"] == "verified":
        record_finding(project_id, "outgoing_security", observation, resolved=True)
    return task_id


def _last_due_window(now: datetime) -> datetime:
    local = now.astimezone(ZoneInfo("America/New_York"))
    end = local.replace(hour=6, minute=0, second=0, microsecond=0)
    if local < end:
        end -= timedelta(days=1)
    return end.replace(hour=2).astimezone(UTC)


def get_project_publication_health(project_id: str, *, now: datetime | None = None,
                                   connection: psycopg.Connection | None = None) -> dict[str, Any]:
    repair = get_repair_task(project_id, connection=connection)
    record = get_latest_backup(project_id=project_id, verification_key="publish_before_backup", connection=connection)
    verification = (record or {}).get("verification_json") or {}
    result = verification.get("publish_before_backup") or verification.get("publication") or {}
    observation = classify_observation(result)
    if not observation["observed_at"]:
        # A backup completion timestamp is not a publication observation timestamp.
        if observation["state"] == "verified":
            observation.update(state="unknown", reason="publication_observation_time_missing")
    elif datetime.fromisoformat(observation["observed_at"]) < _last_due_window(now or datetime.now(UTC)):
        observation.update(state="unknown", reason="nightly_observation_stale")
    findings = ((repair or {}).get("verification_result") or {}).get("publication_repair") or {}
    unresolved = sorted(key for key, finding in findings.items()
                        if isinstance(finding, dict) and finding.get("state") != "resolved")
    if unresolved:
        observation.update(state="blocked", reason="actionable_repair_findings")
    return {"project_id": project_id, **observation, "repair_task_id": (repair or {}).get("id"),
            "unresolved_categories": unresolved, "findings": findings, "backup_id": (record or {}).get("id")}


def repair_attempt_failed(project_id: str, source: str, requested_at: str) -> bool:
    """A fresh conclusive failure containing this candidate ends an async wait."""
    requested = datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
    if requested.tzinfo is None or not _SHA.fullmatch(source):
        return False
    health = get_project_publication_health(project_id)
    observations = list((health.get("findings") or {}).values())
    if health.get("state") == "blocked":
        observations.append(health)
    for finding in observations:
        if not isinstance(finding, dict) or finding.get("state") not in {"unresolved", "blocked"}:
            continue
        try:
            observed = datetime.fromisoformat(str(finding.get("observed_at")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if observed.tzinfo is None or observed <= requested:
            continue
        # An explicitly bound accepted source is useful for a merge analysis;
        # otherwise prove ancestry against the actually observed failure source.
        if finding.get("accepted_source_commit") == source or finding.get("source_commit") == source:
            return True
        tested = finding.get("source_commit")
        if not isinstance(tested, str) or not _SHA.fullmatch(tested):
            continue
        from app.storage.projects import get_project_root_path
        from cli.lib.commit_workflow import run_git
        root = get_project_root_path(project_id)
        if root and run_git(Path(root), ["merge-base", "--is-ancestor", source, tested]).returncode == 0:
            return True
    return False


def confirmation_for_source(project_id: str, source: str, *, health: dict[str, Any] | None = None,
                             connection: psycopg.Connection | None = None) -> dict[str, Any] | None:
    """Confirm the exact repair source is included in the verified nightly source.

The receipt identifies the tested batch head; actual Git ancestry establishes
inclusion rather than relabeling a later source as the accepted revision.
"""
    if not _SHA.fullmatch(source):
        return None
    health = health if health is not None else get_project_publication_health(project_id)
    if health["state"] != "verified" or not health.get("source_commit"):
        return None
    verified = health["source_commit"]
    from app.storage.projects import get_project_root_path
    from cli.lib.commit_workflow import run_git
    root = get_project_root_path(project_id, **({"connection": connection} if connection is not None else {}))
    if not root:
        return None
    if source != verified and run_git(Path(root), ["merge-base", "--is-ancestor", source, verified]).returncode:
        return None
    return {"publication_complete": True, "source_sha": source, "verified_head": verified,
            "source_included": True, "observed_at": health["observed_at"],
            "ci": {"state": "success", "sha": verified}}


def publication_completion_gates(task: dict[str, Any], source: str | None, *,
                                  connection: psycopg.Connection | None = None) -> list[dict[str, Any]]:
    project_id = task.get("project_id")
    if not project_id:
        return []
    health = (get_project_publication_health(str(project_id)) if connection is None
              else get_project_publication_health(str(project_id), connection=connection))
    repair_id = health.get("repair_task_id")
    is_repair = repair_id == task.get("id") or "publication-repair" in (task.get("labels") or [])
    if is_repair:
        if health["unresolved_categories"]:
            return [{"gate": "publication_repair", "pass": False, "detail": health["unresolved_categories"]}]
        confirmation = (confirmation_for_source(str(project_id), source, health=health, connection=connection)
                        if source and connection is not None else confirmation_for_source(str(project_id), source) if source else None)
        if not confirmation:
            return [{"gate": "remote_confirmation", "pass": False,
                     "detail": "Accepted repair source awaits verified nightly remote checks."}]
    elif health["state"] == "blocked" or repair_id:
        return [{"gate": "project_repair", "pass": False,
                 "detail": f"Resolve rolling repair task {repair_id or 'nightly publication defect'} before completion."}]
    return []


def format_publication_health(health: dict[str, Any]) -> str:
    return (f"Nightly publication: {health['state']}; source={str(health.get('source_commit') or 'unknown')[:12]}; "
            f"observed={health.get('observed_at') or 'unknown'}; CI={health.get('ci_state', 'unknown')}; "
            f"reason={health.get('reason', 'unknown')}; repair={health.get('repair_task_id') or 'none'}")
