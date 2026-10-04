"""Read-only, versioned development evidence shared by HTTP and the CLI.

Reads existing stores and local Git objects. Never fetches remote refs, runs
checks, deploys, publishes, captures backups, or persists derived status.
"""
from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.storage import backups, tasks
from app.utils import safe_subprocess
from cli.lib.acceptance import AcceptanceError, _git_common_dir, validate_acceptance_receipt
from cli.lib.service_release import current_source_root, validate_deployment_receipt


def evidence(state: str = "unavailable", *, source_commit: str | None = None,
             observed_at: str | float | None = None, artifact: str | None = None,
             reason: str = "No retained evidence", **details: Any) -> dict[str, Any]:
    return {"state": state, "source_commit": source_commit, "observed_at": observed_at,
            "evidence": artifact, "reason": reason, **details}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError("Evidence must contain an object")
    return value


def _git(root: Path, *args: str) -> str:
    result = safe_subprocess.run(["git", "--no-optional-locks", "-C", str(root), *args],
                                 capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise ValueError("Local Git evidence unavailable")
    return result.stdout.strip()


def _accepted(root: Path, common: Path, head: str) -> dict[str, Any]:
    candidates = []
    unreadable = False
    for path in (common / "st" / "acceptance").glob("*.json"):
        try:
            value = _read(path)
            if value.get("state") == "success" and isinstance(value.get("source"), dict):
                candidates.append((str(value.get("completed_at") or ""), path, value))
        except (OSError, ValueError):
            unreadable = True
    candidates.sort(reverse=True, key=lambda row: row[0])
    # Prefer acceptance for HEAD; retain the latest historical source otherwise.
    selected = next((row for row in candidates if row[2].get("source", {}).get("commit") == head),
                    candidates[0] if candidates else None)
    if not selected:
        return evidence("error" if unreadable else "unavailable", reason="Acceptance receipt unreadable" if unreadable else "No full acceptance recorded")
    _, path, value = selected
    source = value.get("source", {}).get("commit")
    try:
        accepted = validate_acceptance_receipt(root, path)
    except (AcceptanceError, OSError, ValueError):
        return evidence("stale", source_commit=source, observed_at=value.get("completed_at"),
                        artifact=str(path), reason="Retained acceptance does not validate against current source, local inputs or check plan", full_coverage=False, drift=source != head)
    return evidence("accepted" if source == head else "stale", source_commit=source,
                    observed_at=accepted.get("completed_at"), artifact=str(path),
                    reason="Full local acceptance" if source == head else "Accepted source differs from working HEAD",
                    full_coverage=True, check_count=accepted.get("check_count"), drift=source != head)


def _native_metadata_project(path: Path) -> str | None:
    """Rejected private receipt metadata can attribute uncertainty, never success."""
    try:
        # Match the owning reader's private server-state contract before
        # inspecting metadata from a record it could not authenticate.
        for candidate in (path.parent, path):
            if candidate.is_symlink() or candidate.stat().st_uid != os.getuid() or candidate.stat().st_mode & 0o077:
                return None
        if not path.is_file():
            return None
        project = _read(path).get("project")
        return project if isinstance(project, str) and project else None
    except (OSError, ValueError):
        return None


def _running(project_id: str, root: Path, accepted: dict[str, Any]) -> dict[str, Any]:
    try:
        source_root = current_source_root(project_id)
        if source_root:
            path = source_root.parents[2] / "receipts" / f"{source_root.parent.name}.json"
            # The current pointer selects the last health-verified release.
            receipt = validate_deployment_receipt(path, project_root=root)
            raw = _read(path)
            return evidence("observed", source_commit=receipt["source_commit"],
                            observed_at=raw.get("completed_at"), artifact=str(path),
                            reason="Health verified at deployment; current live health not polled",
                            runtime_health="recorded_success", drift=bool(accepted.get("source_commit")) and receipt["source_commit"] != accepted["source_commit"])
        from app.services.native_deployment import _record_path, _store_root, read_native_evidence
        native: list[dict[str, Any]] = []
        invalid_matching: list[str] = []
        invalid_foreign = 0
        invalid_unassignable = 0
        for path in _store_root().glob("*.json"):
            if not re.fullmatch(r"[0-9a-f]{32}", path.stem):
                continue
            record = None
            try:
                record = read_native_evidence(path.stem)
                if record.get("project") != project_id:
                    continue
                source = record["observation"]["deployed_source_commit"]
                completed_at = record["completed_at"]
                if (record["state"] not in {"succeeded", "failed"}
                        or not isinstance(source, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", source)
                        or not isinstance(completed_at, (int, float)) or isinstance(completed_at, bool)):
                    raise ValueError("Native runtime observation is incomplete")
                native.append(record)
            except (OSError, ValueError, RuntimeError, KeyError, TypeError):
                owner = record.get("project") if record is not None else _native_metadata_project(path)
                if owner == project_id:
                    invalid_matching.append(str(path))
                elif isinstance(owner, str) and owner:
                    invalid_foreign += 1
                else:
                    invalid_unassignable += 1
        result = evidence(reason="No deployment observation recorded", runtime_health="unknown")
        if native:
            record = max(native, key=lambda item: item["completed_at"])
            source = record["observation"]["deployed_source_commit"]
            result = evidence(record["state"], source_commit=source, observed_at=record["completed_at"],
                              artifact=str(_record_path(record["receipt_id"])), reason="Retained native runtime observation; current live health not polled",
                              runtime_health="recorded_success" if record["state"] == "succeeded" else "recorded_failure",
                              drift=bool(accepted.get("source_commit")) and source != accepted["source_commit"])
        invalid_count = len(invalid_matching) + invalid_foreign + invalid_unassignable
        if invalid_count:
            noun = "receipt" if invalid_count == 1 else "receipts"
            note = f"Shared deployment evidence includes {invalid_count} {noun} that could not be validated."
            integrity = evidence("uncertain", reason=note, invalid_records=invalid_count,
                                 matching_records=len(invalid_matching), foreign_records=invalid_foreign,
                                 unassignable_records=invalid_unassignable)
            if invalid_matching:
                prior = result
                result = evidence("error", reason="Deployment evidence for this project could not be validated", runtime_health="unknown",
                                  invalid_evidence=invalid_matching)
                if native:
                    result["validated_observation"] = prior
            result["reason"] = result["reason"].rstrip(".") + ". " + note
            result["shared_store_integrity"] = integrity
        return result
    except (OSError, ValueError, RuntimeError, KeyError):
        return evidence("error", reason="Deployment observation could not be validated", runtime_health="unknown")


def _recovery(project_id: str) -> dict[str, dict[str, Any]]:
    result = {key: evidence() for key in ("capture", "offsite", "snapshot", "restore")}
    try:
        records, total = backups.list_backups(project_id=project_id, limit=50)
        sources = [source for source in backups.list_sources() if source.get("project_id") == project_id]
        if records:
            row = records[0]
            verification = row.get("verification_json") or {}
            if isinstance(verification, str):
                verification = json.loads(verification)
            recovery = verification.get("recovery") or {}
            git = recovery.get("git") or {}
            common = {"source_commit": git.get("head"), "observed_at": row.get("completed_at") or row.get("created_at"), "artifact": row["id"]}
            result["capture"] = evidence(str(row["status"]), reason="Latest backup capture", backup_count=total, **common)
            offsite = verification.get("offsite") or {}
            result["offsite"] = evidence(str(offsite.get("status") or "unavailable"),
                                          reason=str(offsite.get("error") or "Offsite copy evidence"), **common)
            snapshot = next((item for item in records if isinstance(item.get("verification_json"), dict) and item["verification_json"].get("snapshot_id")), None)
            snapshot_id = snapshot["verification_json"]["snapshot_id"] if snapshot else None
            result["snapshot"] = evidence("recorded" if snapshot_id else "unavailable",
                                           reason="Latest retained repository snapshot" if snapshot_id else "No repository snapshot recorded in recent backups",
                                           snapshot_id=snapshot_id, observed_at=snapshot.get("completed_at") if snapshot else None,
                                           artifact=str(snapshot["id"]) if snapshot else None)
        drills = [source for source in sources if source.get("last_drill_at")]
        if drills:
            drill = max(drills, key=lambda item: str(item["last_drill_at"]))
            result["restore"] = evidence("verified" if drill.get("last_drill_ok") is True else "failed" if drill.get("last_drill_ok") is False else "unknown",
                                          observed_at=drill["last_drill_at"], artifact=drill.get("last_drill_backup_id"), reason="Recorded restore drill")
    except (OSError, ValueError, RuntimeError):
        return {key: evidence("error", reason="Backup evidence unavailable") for key in result}
    return result


def _publication(root: Path, common: Path, project_id: str) -> dict[str, Any]:
    from app.tasks.backup_manual_publish import latest_publication_receipt

    retained = latest_publication_receipt(root, project_id, directory=common / "st" / "publication")
    if retained is None:
        return evidence(reason="No manual publication recorded")
    path, value = retained
    observation = value.get("observation") or {}
    return evidence(str(observation.get("status") or "unknown"), source_commit=value.get("source_commit"),
                    observed_at=value.get("observed_at"), artifact=str(path),
                    reason=str(observation.get("reason") or "Manual publication observation"),
                    pushed=bool(observation.get("pushed")), publication_complete=bool(observation.get("publication_complete")),
                    delivery=observation.get("delivery"), optional_cloud=(observation.get("ci") or {}).get("optional_state", "unknown"))


def build_development_projection(project_id: str, project_root: Path) -> dict[str, Any]:
    """Return local evidence with independent failure states; writes no status store."""
    result: dict[str, Any] = {"version": "development.v1", "project_id": project_id,
                             "observed_at": datetime.now(UTC).isoformat()}
    try:
        head = _git(project_root, "rev-parse", "HEAD")
        common = _git_common_dir(project_root)
        status = _git(project_root, "status", "--porcelain", "--untracked-files=all")
        ahead = _git(project_root, "rev-list", "--count", "@{upstream}..HEAD") if _has_upstream(project_root) else None
        result["working_tree"] = evidence("uncommitted" if status else "clean", source_commit=head,
                                           observed_at=result["observed_at"], reason="Local working tree",
                                           uncommitted=len(status.splitlines()) if status else 0,
                                           unpublished=int(ahead) if ahead is not None else None,
                                           remote_basis="Local remote refs; refresh explicitly")
        try:
            result["accepted"] = _accepted(project_root, common, head)
        except Exception:
            result["accepted"] = evidence("error", reason="Acceptance evidence unavailable")
        try:
            result["publication"] = _publication(project_root, common, project_id)
        except (OSError, ValueError):
            result["publication"] = evidence("error", reason="Publication receipt unreadable")
    except (OSError, ValueError, RuntimeError):
        result.update(working_tree=evidence("error", reason="Local Git evidence unavailable"), accepted=evidence("unavailable", reason="Local Git evidence unavailable"), publication=evidence("unavailable", reason="Local Git evidence unavailable"))
    try:
        blocked = tasks.list_blocked_tasks(project_id, limit=500)
        failed = tasks.list_tasks(project_id, status_filter="failed", limit=500)
        pending = tasks.list_tasks(project_id, status_filter="pending", limit=500)
        running = tasks.list_tasks(project_id, status_filter="running", limit=500)
        partial = any(len(rows) == 500 for rows in (blocked, failed, pending, running))
        from app.storage.tasks.publication_repair import unresolved_repair

        items: dict[str, dict[str, Any]] = {}
        for row in blocked:
            items[row["id"]] = {"task_id": row["id"], "title": row.get("title") or row["id"],
                "status": row["status"], "reason": "A task dependency remains incomplete"}
        for row in [*pending, *running, *failed]:
            closeout = (row.get("verification_result") or {}).get("closeout") or {}
            findings = unresolved_repair(row)
            reason = (closeout.get("reason") if closeout.get("kind") == "local_closeout.v1" and closeout.get("state") == "blocked" else None)
            if not reason and findings:
                reason = "Retained findings need investigation: " + ", ".join(findings)
            if not reason and row["status"] == "failed":
                reason = row.get("error_message") or "Task needs review"
            if reason:
                items[row["id"]] = {"task_id": row["id"], "title": row.get("title") or row["id"],
                    "status": row["status"], "reason": reason}
        result["blockers"] = {"state": "partial" if partial else "available", "items": list(items.values())}
        if partial:
            result["blockers"]["reason"] = "Showing the first 500 tasks per blocker state"
    except Exception:
        result["blockers"] = {"state": "unavailable", "items": [], "reason": "Task store unavailable"}
    result["running"] = _running(project_id, project_root, result["accepted"])
    try:
        result["recovery"] = _recovery(project_id)
    except Exception:
        result["recovery"] = {key: evidence("unavailable", reason="Backup store unavailable") for key in ("capture", "offsite", "snapshot", "restore")}
    return result


def _has_upstream(root: Path) -> bool:
    try:
        _git(root, "rev-parse", "--verify", "@{upstream}")
        return True
    except ValueError:
        return False
