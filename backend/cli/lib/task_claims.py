"""Owned task-claim renewal for explicit local development activity.

Renewal is deliberately activity-bound: more than 30 minutes of editing or
thinking without an owned ST task action can still expire a manual claim.
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from ..config import Config, get_config_optional


class TaskClaimRenewalError(RuntimeError):
    """Raised when active work cannot safely renew its exact task claim."""


def current_caller_identity() -> dict[str, str]:
    """Normalize one opaque owner ID and optional native session telemetry.

    Full session identifiers distinguish roots sharing a host or prefix. Legacy
    callers without a stable native session retain their hostname identity;
    hostname-owned claims are never implicitly adopted by a native session.
    """
    from .leases import identify_agent

    _, slug, session_id, provider = identify_agent(native=False)
    if provider != "unknown":
        return {"member_id": f"{provider}:{slug}:{session_id}",
                "provider": provider, "session_id": session_id}
    return {"member_id": socket.gethostname(), "provider": "hostname"}


def current_worker_id() -> str:
    """Return the opaque owner identity shared by claim and closeout paths."""
    return current_caller_identity()["member_id"]


def _renewal_config(repo: Path) -> tuple[Config, bool]:
    config = get_config_optional()
    if config is None:
        raise TaskClaimRenewalError("cannot renew task claim without local project configuration")
    api_host = (urlparse(config.api_base).hostname or "").lower()
    if not config.project_root or Path(config.project_root).resolve() != repo.resolve():
        raise TaskClaimRenewalError("task claim project does not match this checkout")
    return config, api_host in {"localhost", "127.0.0.1", "::1"}


def renew_local_owned_claim(repo: Path, task_id: str) -> dict[str, object]:
    """Renew through the local store only after proving its project identity."""
    config, is_loopback = _renewal_config(repo)
    if not is_loopback:
        raise TaskClaimRenewalError("cannot use local claim renewal for a remote ST API")

    from app.storage import tasks as task_store
    from app.storage.projects import get_project_root_path

    stored_root = get_project_root_path(config.project_id)
    if not stored_root or Path(stored_root).resolve() != repo.resolve():
        raise TaskClaimRenewalError("local task store project does not match this checkout")
    task = task_store.get_task(task_id)
    if task is None or task.get("project_id") != config.project_id:
        raise TaskClaimRenewalError("task claim does not belong to this configured project")
    renewed = task_store.renew_task_claim(task_id, current_worker_id())
    if renewed is None:
        raise TaskClaimRenewalError(
            "task claim is not actively owned by this worker; run st claim before continuing"
        )
    return renewed


def renew_owned_claim(repo: Path, task_id: str) -> dict[str, object]:
    """Renew through the public API, with a loopback-only rollout fallback."""
    config, is_loopback = _renewal_config(repo)
    worker_id = current_worker_id()

    from ..client import APIError, STClient

    client = STClient(base_url=config.api_base, project_id=config.project_id)
    task = client.get_task(task_id)
    if (
        task.get("project_id") != config.project_id
        or task.get("status") != "running"
        or task.get("claimed_by") != worker_id
    ):
        raise TaskClaimRenewalError(
            "task claim is not actively owned by this worker; run st claim before continuing"
        )
    try:
        renewed = client.claim_task(task_id, worker_id=worker_id, renew_only=True)
        # Older loopback servers omit claimed_at from their response model.
        # Capture the exact local claim before running checks, with the same
        # registered-root authority used by the rollout fallback.
        if is_loopback and not renewed.get("claimed_at"):
            from app.storage.projects import get_project_root_path
            from app.storage.tasks import get_task
            root = get_project_root_path(config.project_id)
            current = get_task(task_id)
            if (not root or Path(root).resolve() != repo.resolve() or not current
                    or current.get("project_id") != config.project_id
                    or current.get("status") != "running" or current.get("claimed_by") != worker_id):
                raise TaskClaimRenewalError("local claim identity changed before acceptance")
            renewed = {**renewed, "claimed_at": current["claimed_at"],
                       "verification_result": current.get("verification_result")}
        return renewed
    except APIError as exc:
        if exc.status_code == 409 and is_loopback:
            return renew_local_owned_claim(repo, task_id)
        if exc.status_code == 409:
            raise TaskClaimRenewalError(
                "remote ST API does not support safe same-owner claim renewal; upgrade it first"
            ) from exc
        raise TaskClaimRenewalError(f"task claim renewal failed: {exc.detail}") from exc


def attach_owned_acceptance(repo: Path, task: dict[str, object], receipt: dict[str, object]) -> bool:
    """Local proof attachment never writes a different server's task database."""
    config, is_loopback = _renewal_config(repo)
    if not is_loopback:
        return False  # The immutable local artifact remains available for import.
    from app.storage.projects import get_project_root_path
    from app.storage.tasks.closeout import store_owned_acceptance

    root = get_project_root_path(config.project_id)
    if (not root or Path(root).resolve() != repo.resolve()
            or task.get("project_id") != config.project_id
            or task.get("claimed_by") != current_worker_id()):
        raise TaskClaimRenewalError("acceptance attachment does not match this local project claim")
    verification: Any = task.get("verification_result") or {}
    if not isinstance(verification, dict):
        raise TaskClaimRenewalError("acceptance attachment has no valid prior evidence revision")
    prior = cast(dict[str, Any], verification)
    return store_owned_acceptance(str(task["id"]), config.project_id, receipt,
        expected_worker=current_worker_id(), expected_claimed_at=task.get("claimed_at"),
        expected_acceptance=prior.get("acceptance") or {})
