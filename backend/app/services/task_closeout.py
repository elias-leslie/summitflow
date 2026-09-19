"""Resume an explicitly requested closeout against its immutable source revision.

This never commits a working tree or reruns completed local gates. The existing
GitHub publisher owns repository rules, exact-head checks, and merge behavior.
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.storage.tasks import get_task
from app.storage.tasks.closeout import closeout_lock, pending_closeout_ids, store_closeout


def request_closeout(task_id: str, project_id: str, *, source_sha: str,
                     message: str | None, paths: tuple[str, ...] = ()) -> dict[str, Any]:
    """Called only after canonical local quality, diff and readiness gates pass."""
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", source_sha):
        raise ValueError("Closeout requires a full immutable source commit")
    with closeout_lock(task_id) as acquired:
        if not acquired:
            return {"action": "pending", "task_id": task_id, "reason": "closeout_in_progress"}
        task = get_task(task_id)
        if not task or task["project_id"] != project_id:
            raise ValueError("Closeout task/project mismatch")
        previous = (task.get("verification_result") or {}).get("closeout") or {}
        if previous.get("state") == "pending":
            if previous["source_sha"] != source_sha:
                raise ValueError("An earlier exact-source closeout is still pending")
            return previous
        intent = {"request_id": str(uuid.uuid4()), "state": "pending", "source_sha": source_sha,
                  "project_id": project_id, "task_id": task_id, "message": message or task["title"],
                  "paths": list(paths), "requested_at": datetime.now(UTC).isoformat(),
                  "local_gates": "canonical_done_prerequisites_satisfied"}
        store_closeout(task_id, project_id, intent)
        from app.storage.events import log_task_event
        log_task_event(task_id, f"Completion requested for {source_sha}; remote checks will continue automatically.")
        return intent


def get_closeout(task_id: str) -> dict[str, Any] | None:
    task = get_task(task_id)
    return ((task or {}).get("verification_result") or {}).get("closeout")


def pending_closeouts() -> list[dict[str, str]]:
    return [{"task_id": task_id, "project_id": intent["project_id"]}
            for task_id in pending_closeout_ids() if (intent := get_closeout(task_id))]


def resume_closeout(task_id: str, *, explicit: bool = False) -> dict[str, Any]:
    """One observation/transition; the existing schedule continues pending CI."""
    from app.storage.events import log_task_event
    from app.storage.projects import get_project_root_path
    from app.tasks.autonomous.cleanup import cleanup_task_checkpoint
    from cli.client import STClient
    from cli.lib.commit_workflow import _record_task_publication, run_git
    from cli.lib.publish_workflow import publish_git

    with closeout_lock(task_id) as acquired:
        if not acquired:
            return {"action": "pending", "task_id": task_id, "reason": "closeout_in_progress"}
        task = get_task(task_id)
        intent = ((task or {}).get("verification_result") or {}).get("closeout") or {}
        if not task or not intent:
            return {"action": "skipped", "task_id": task_id, "reason": "no_completion_request"}
        if task["status"] in {"paused", "cancelled", "abandoned", "closed", "failed"}:
            return {"action": "skipped", "task_id": task_id, "reason": "task_not_active"}
        if intent["state"] == "complete":
            return {"action": "completed", "task_id": task_id, "snapshot_removed": True}
        if intent["state"] == "blocked" and not explicit:
            return {"action": "blocked", "task_id": task_id, "reason": intent.get("reason")}
        request_id = str(intent["request_id"])
        project_id = task["project_id"]
        root = get_project_root_path(project_id)
        if not root or intent["project_id"] != project_id:
            raise ValueError("Closeout project identity changed")
        result: dict[str, Any] = {}
        previous_state = intent["state"]
        try:
            if not (intent.get("publication") or {}).get("publication_complete"):
                result = publish_git(Path(root), sha=intent["source_sha"], task_id=task_id,
                                     message=str(intent["message"]), run_git=run_git, resume=True)
                result = _record_task_publication(Path(root), result, task_id=task_id, push=True)
                intent = {**intent, "publication": result, "observed_at": datetime.now(UTC).isoformat()}
                if not result.get("publication_complete"):
                    state = "pending" if result.get("status") == "PENDING" else "blocked"
                    intent.update(state=state, reason=result.get("reason") or "publication_unavailable")
                    if not store_closeout(task_id, project_id, intent, expected_request_id=request_id):
                        return {"action": "skipped", "task_id": task_id, "reason": "completion_request_superseded"}
                    if state != previous_state:
                        log_task_event(task_id, f"Closeout {state}: {intent['reason']}")
                    return {"action": state, "task_id": task_id, "project_id": project_id,
                            "reason": intent["reason"], "publication": result}
                # Persist successful evidence before finalization, so a crash between
                # status update and metadata cleanup can resume without republishing.
                if not store_closeout(task_id, project_id, intent, expected_request_id=request_id):
                    return {"action": "skipped", "task_id": task_id, "reason": "completion_request_superseded"}
            current = get_task(task_id)
            if not current or current["status"] in {"paused", "cancelled", "abandoned", "closed", "failed"}:
                return {"action": "skipped", "task_id": task_id, "reason": "task_not_active"}
            if current["status"] != "completed":
                from cli.commands.done_task import _auto_verify_readiness
                client = STClient(project_id=project_id)
                _auto_verify_readiness(client, task_id)
                from app.storage.tasks import update_task_status
                update_task_status(task_id, "completed", validate_transition=False,
                                   expected_closeout_request_id=request_id)
            cleanup = cleanup_task_checkpoint(task_id, project_id=project_id)
            if cleanup["status"] != "cleaned" and cleanup.get("reason") != "no_checkpoint":
                raise RuntimeError(f"Checkpoint cleanup did not complete: {cleanup}")
            from cli.commands.done import _release_task_leases
            _release_task_leases(project_id, task_id)
            intent.update(state="complete", completed_at=datetime.now(UTC).isoformat(), reason="")
            if not store_closeout(task_id, project_id, intent, expected_request_id=request_id):
                return {"action": "skipped", "task_id": task_id, "reason": "completion_request_superseded"}
            log_task_event(task_id, "Closeout completed automatically from retained source and publication evidence.")
            return {"action": "completed", "task_id": task_id, "project_id": project_id,
                    "snapshot_removed": True, "published": True,
                    "base_branch": task.get("base_branch") or "main"}
        except Exception as exc:
            intent.update(state="blocked", reason=str(exc), observed_at=datetime.now(UTC).isoformat())
            if not store_closeout(task_id, project_id, intent, expected_request_id=request_id):
                return {"action": "skipped", "task_id": task_id, "reason": "completion_request_superseded"}
            if previous_state != "blocked":
                log_task_event(task_id, f"Closeout needs attention: {exc}")
            return {"action": "blocked", "task_id": task_id, "project_id": project_id, "reason": str(exc)}


def checkpoint_state(status: str, verification: dict[str, Any] | None) -> tuple[str, str]:
    """Shared UI/CLI description; a checkpoint does not prove a live agent."""
    verification = verification or {}
    closeout = verification.get("closeout") or {}
    publication = verification.get("publication") or {}
    if closeout.get("state") == "pending":
        return "waiting_checks", "Publication closeout continues automatically"
    if closeout.get("state") == "blocked" or (publication.get("ci") or {}).get("state") == "failed":
        return "blocked", closeout.get("reason") or "Retained publication checks need investigation"
    return ("claimed" if status == "running" else "open"), "Open task checkpoint; this does not establish a live agent session"
