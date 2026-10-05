"""Source-bound local completion and recoverable checkpoint cleanup.

Legacy remote requests are historical evidence. Resuming them requires an
explicit local completion request; no continuation contacts a remote service.
"""
from __future__ import annotations

import re
import uuid
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from app.storage.tasks import get_task
from app.storage.tasks.closeout import (
    closeout_lock,
    finish_closeout_cleanup,
    pending_closeout_ids,
    store_closeout,
)


class CloseoutOperations(Protocol):
    """The local filesystem adapter needed by the task completion module."""

    def caller_identity(self) -> str: ...
    def source_lock(self, root: Path) -> AbstractContextManager[None]: ...
    def validate_source(self, root: Path, acceptance: dict[str, Any], source_sha: str) -> dict[str, Any]: ...
    def require_owned_source(self, root: Path, source_sha: str, paths: tuple[str, ...], task: dict[str, Any]) -> None: ...
    def cleanup(self, task_id: str, project_id: str, root: Path) -> None: ...


def _closeout_operations() -> CloseoutOperations:
    # The CLI owns local Git/checkpoint infrastructure. Its explicit adapter
    # keeps command handlers and presentation helpers out of task policy.
    from cli.lib.task_closeout_adapter import LocalCloseoutOperations

    return LocalCloseoutOperations()


def _require_selected_reference(acceptance: dict[str, Any], validated: dict[str, Any], paths: tuple[str, ...]) -> None:
    """The retained descriptor must describe the proof actually validated."""
    for key in ("acceptance_id", "source_commit", "source_tree", "coverage", "input_fingerprint",
                "acceptance_plan_fingerprint", "required_stages", "scope_digest"):
        if key in acceptance and acceptance[key] != validated.get(key):
            raise ValueError(f"Closeout acceptance reference changed: {key}")
    if validated.get("coverage") == "task":
        scope = validated.get("scope")
        if not isinstance(scope, list) or scope != sorted(set(paths)) or acceptance.get("scope") != scope:
            raise ValueError("Task acceptance scope differs from selected closeout paths")


def completion_evidence(acceptance: dict[str, Any], *, source_sha: str | None = None,
                        retained: bool = False, record_only: bool = False) -> dict[str, str]:
    """Project selected completion evidence without reading or validating new data."""
    if record_only:
        return {"source_commit": "not_applicable", "evidence_basis": "not_applicable"}
    source = acceptance.get("source_commit")
    selected = (acceptance.get("state") == "success" and isinstance(source, str)
                and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", source)
                and (source_sha is None or source == source_sha))
    result: dict[str, str] = {"source_commit": source if selected and isinstance(source, str) else "unknown",
              "evidence_basis": "retained" if retained else "validated" if selected else "unknown"}
    if selected:
        for key in ("acceptance_id", "acceptance_artifact", "coverage", "outcome"):
            value = acceptance.get(key)
            if isinstance(value, str) and value:
                result[key] = value
    return result


def request_closeout(task_id: str, project_id: str, *, source_sha: str,
                     message: str | None, paths: tuple[str, ...] = (),
                     expected_worker: str | None = None, expected_claimed_at: Any = None,
                     expected_acceptance: dict[str, Any] | None = None,
                     expected_verification: dict[str, Any] | None = None,
                     operations: CloseoutOperations | None = None) -> dict[str, Any]:
    """Retain local prerequisites before a status update or cleanup can fail."""
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", source_sha):
        raise ValueError("Closeout requires a full immutable source commit")
    with closeout_lock(task_id) as acquired:
        if not acquired:
            return {"action": "pending", "task_id": task_id, "reason": "closeout_in_progress"}
        task = get_task(task_id)
        if not task or task["project_id"] != project_id:
            raise ValueError("Closeout task/project mismatch")
        if task["status"] not in {"running", "pending", "completed"}:
            raise ValueError("Local completion requires an active or completed task")
        acceptance = (task.get("verification_result") or {}).get("acceptance") or {}
        if acceptance.get("state") != "success" or acceptance.get("source_commit") != source_sha:
            raise ValueError("Closeout requires successful acceptance for the requested source")
        previous = (task.get("verification_result") or {}).get("closeout") or {}
        if previous.get("kind") == "local_closeout.v1" and previous.get("state") in {"pending", "blocked"}:
            if previous["source_sha"] != source_sha:
                raise ValueError("An earlier exact-source closeout remains unresolved")
            return previous
        local = operations or _closeout_operations()
        if (not expected_worker or expected_worker != local.caller_identity() or not expected_claimed_at
                or task["status"] != "running" or task.get("claimed_by") != expected_worker
                or datetime.fromisoformat(str(task.get("claimed_at"))) != datetime.fromisoformat(str(expected_claimed_at))):
            raise ValueError("Local completion requires the same active claim that accepted this work")
        if expected_acceptance is None or acceptance != expected_acceptance:
            raise ValueError("Local completion acceptance changed after its prerequisite gates")
        intent = {"kind": "local_closeout.v1", "request_id": str(uuid.uuid4()),
                  "state": "pending", "source_sha": source_sha,
                  "project_id": project_id, "task_id": task_id, "message": message or task["title"],
                  "paths": list(paths), "requested_at": datetime.now(UTC).isoformat(),
                  "local_gates": "canonical_done_prerequisites_satisfied"}
        if previous:
            intent["previous_closeout"] = previous
        if not store_closeout(task_id, project_id, intent, expected_closeout=previous, expected_source_sha=source_sha,
                expected_worker=expected_worker, expected_claimed_at=expected_claimed_at,
                expected_acceptance=expected_acceptance, expected_verification=expected_verification):
            return {"action": "skipped", "task_id": task_id, "reason": "completion_request_superseded"}
        from app.storage.events import log_task_event
        log_task_event(task_id, f"Local completion requested for {source_sha}; cleanup is recoverable.")
        return intent


def get_closeout(task_id: str) -> dict[str, Any] | None:
    task = get_task(task_id)
    return ((task or {}).get("verification_result") or {}).get("closeout")


def pending_closeouts() -> list[dict[str, str]]:
    return [{"task_id": task_id, "project_id": intent["project_id"]}
            for task_id in pending_closeout_ids() if (intent := get_closeout(task_id))]


def resume_closeout(task_id: str, *, explicit: bool = False,
                    operations: CloseoutOperations | None = None) -> dict[str, Any]:
    """Recover local cleanup only; never publish, commit, deploy or change source."""
    from app.services.task_acceptance import load_completion_assessment
    from app.storage.events import log_task_event
    from app.storage.projects import get_project_root_path

    with closeout_lock(task_id) as acquired:
        if not acquired:
            return {"action": "pending", "task_id": task_id, "reason": "closeout_in_progress"}
        task = get_task(task_id)
        intent = ((task or {}).get("verification_result") or {}).get("closeout") or {}
        if not task or not intent:
            return {"action": "skipped", "task_id": task_id, "reason": "no_completion_request"}
        if intent.get("kind") != "local_closeout.v1":
            return {"action": "skipped", "task_id": task_id, "reason":
                    "historical_closeout_inactive" if intent.get("kind") == "lifecycle_closeout_history.v1" else "legacy_remote_closeout_retired"}
        if task["status"] not in {"pending", "running", "completed"}:
            return {"action": "skipped", "task_id": task_id, "reason": "task_not_active"}
        if intent["state"] == "complete":
            if task["status"] != "completed":
                return {"action": "skipped", "task_id": task_id, "reason": "completed_request_no_longer_current"}
            acceptance = (task.get("verification_result") or {}).get("acceptance") or {}
            return {"action": "completed", "task_id": task_id, "snapshot_removed": True, "published": False,
                    "base_branch": task.get("base_branch") or "main",
                    **completion_evidence(acceptance, source_sha=intent["source_sha"], retained=True)}
        if intent["state"] == "blocked" and not explicit:
            return {"action": "blocked", "task_id": task_id, "reason": intent.get("reason")}
        request_id = str(intent["request_id"])
        project_id = task["project_id"]
        previous_state = intent["state"]
        try:
            root = get_project_root_path(project_id)
            if not root or intent["project_id"] != project_id:
                raise ValueError("Closeout project identity changed")
            acceptance = (task.get("verification_result") or {}).get("acceptance") or {}
            if acceptance.get("state") != "success" or acceptance.get("source_commit") != intent["source_sha"]:
                raise ValueError("Closeout acceptance source changed")
            local = operations or _closeout_operations()
            with local.source_lock(Path(root)):
                # Completed status already passed the owner contract; recovery
                # removes metadata only and may coexist with later local work.
                if task["status"] != "completed":
                    validated = local.validate_source(Path(root), acceptance, intent["source_sha"])
                    _require_selected_reference(acceptance, validated, tuple(intent.get("paths") or ()))
                    local.require_owned_source(Path(root), intent["source_sha"], tuple(intent.get("paths") or ()), task)
                    assessment = load_completion_assessment(task_id)
                    if not assessment.complete:
                        raise ValueError(f"Task not ready to complete: {list(assessment.gates)}")
                    from app.storage.tasks import update_task_status
                    update_task_status(task_id, "completed", validate_transition=False,
                                       expected_closeout_request_id=request_id)
                def cleanup() -> None:
                    local.cleanup(task_id, project_id, Path(root))

                if not finish_closeout_cleanup(task_id, project_id, request_id, intent["source_sha"], cleanup):
                    return {"action": "skipped", "task_id": task_id, "reason": "completion_request_superseded"}
            log_task_event(task_id, "Local closeout cleanup completed from retained source-bound acceptance.")
            return {"action": "completed", "task_id": task_id, "project_id": project_id,
                    "snapshot_removed": True, "published": False,
                    "base_branch": task.get("base_branch") or "main",
                    **completion_evidence(acceptance, source_sha=intent["source_sha"],
                                          retained=task["status"] == "completed")}
        except Exception as exc:
            intent.update(state="blocked", reason=str(exc), observed_at=datetime.now(UTC).isoformat())
            if not store_closeout(task_id, project_id, intent, expected_request_id=request_id):
                return {"action": "skipped", "task_id": task_id, "reason": "completion_request_superseded"}
            if previous_state != "blocked":
                log_task_event(task_id, f"Local closeout needs attention: {exc}")
            return {"action": "blocked", "task_id": task_id, "project_id": project_id, "reason": str(exc)}


def checkpoint_state(status: str, verification: dict[str, Any] | None) -> tuple[str, str]:
    """Describe local task state; retained publication history does not gate it."""
    verification = verification or {}
    closeout = verification.get("closeout") or {}
    if status == "completed":
        if closeout.get("kind") == "local_closeout.v1" and closeout.get("state") in {"pending", "blocked"}:
            return "cleanup_pending", "Completed locally; checkpoint cleanup remains recoverable"
        return "complete", "Completed locally; publication is independent"
    if closeout.get("kind") == "local_closeout.v1" and closeout.get("state") == "blocked":
        return "blocked", closeout.get("reason") or "Local closeout needs attention"
    return ("claimed" if status == "running" else "open"), "Open task checkpoint; this does not establish a live agent session"
