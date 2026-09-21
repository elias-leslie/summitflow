"""Owned task-claim renewal for explicit local development activity.

Renewal is deliberately activity-bound: more than 30 minutes of editing or
thinking without an owned ST task action can still expire a manual claim.
"""

from __future__ import annotations

import socket
from pathlib import Path
from urllib.parse import urlparse

from ..config import Config, get_config_optional


class TaskClaimRenewalError(RuntimeError):
    """Raised when active work cannot safely renew its exact task claim."""


def current_worker_id() -> str:
    """Return the same default identity used by the public claim client."""
    return socket.gethostname()


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
        return client.claim_task(task_id, worker_id=worker_id, renew_only=True)
    except APIError as exc:
        if exc.status_code == 409 and is_loopback:
            return renew_local_owned_claim(repo, task_id)
        if exc.status_code == 409:
            raise TaskClaimRenewalError(
                "remote ST API does not support safe same-owner claim renewal; upgrade it first"
            ) from exc
        raise TaskClaimRenewalError(f"task claim renewal failed: {exc.detail}") from exc
