"""Docker artifact pruning helpers for host retention."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from datetime import datetime
from typing import TypedDict

from ._retention_policy import HostRetentionPolicy

_ANON_DOCKER_VOLUME_RE = re.compile(r"^[0-9a-f]{64}$")
_RunFn = Callable[..., subprocess.CompletedProcess[str]]


class CacheResult(TypedDict, total=False):
    status: str
    target_gb: int
    stdout_tail: str
    error: str
    reason: str


class ImageResult(TypedDict, total=False):
    status: str
    max_age_hours: int
    stdout_tail: str
    error: str
    reason: str


class VolumeResult(TypedDict, total=False):
    status: str
    deleted: list[str]
    skipped: list[str]
    error: str
    reason: str


def _tail(text: str, *, limit: int = 400) -> str:
    return text.strip()[-limit:] if text else ""


def prune_builder_cache(
    *,
    policy: HostRetentionPolicy,
    pressure_mode: bool,
    run: _RunFn,
) -> CacheResult:
    target_gb = (
        policy.builder_cache_pressure_target_gb if pressure_mode else policy.builder_cache_target_gb
    )
    proc = run(
        ["docker", "builder", "prune", "--force", "--all", "--keep-storage", f"{target_gb}gb"],
        timeout=300,
    )
    if proc.returncode != 0:
        return {"status": "error", "target_gb": target_gb, "error": _tail(proc.stderr or proc.stdout)}
    return {"status": "success", "target_gb": target_gb, "stdout_tail": _tail(proc.stdout)}


def prune_images(
    *,
    policy: HostRetentionPolicy,
    pressure_mode: bool,
    run: _RunFn,
) -> ImageResult:
    max_age_hours = (
        policy.image_pressure_max_age_hours if pressure_mode else policy.image_max_age_hours
    )
    args = ["docker", "image", "prune", "--force", "--all"]
    if max_age_hours > 0:
        args.extend(["--filter", f"until={max_age_hours}h"])
    proc = run(args, timeout=300)
    if proc.returncode != 0:
        return {"status": "error", "max_age_hours": max_age_hours, "error": _tail(proc.stderr or proc.stdout)}
    return {"status": "success", "max_age_hours": max_age_hours, "stdout_tail": _tail(proc.stdout)}


def _inspect_volume_created_at(name: str, run: _RunFn) -> datetime | None:
    proc = run(["docker", "volume", "inspect", name], timeout=60)
    if proc.returncode != 0:
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list) or not payload:
        return None
    raw_created = str(payload[0].get("CreatedAt", "")).strip()
    if not raw_created:
        return None
    try:
        return datetime.fromisoformat(raw_created.replace("Z", "+00:00"))
    except ValueError:
        return None


def prune_anonymous_docker_volumes(
    *,
    policy: HostRetentionPolicy,
    now: datetime,
    run: _RunFn,
) -> VolumeResult:
    proc = run(["docker", "volume", "ls", "-q", "-f", "dangling=true"], timeout=60)
    if proc.returncode != 0:
        return {"status": "error", "deleted": [], "error": _tail(proc.stderr or proc.stdout)}

    deleted: list[str] = []
    skipped: list[str] = []
    for raw_name in proc.stdout.splitlines():
        name = raw_name.strip()
        if not name:
            continue
        if not _ANON_DOCKER_VOLUME_RE.fullmatch(name):
            skipped.append(name)
            continue
        created_at = _inspect_volume_created_at(name, run)
        if created_at is None:
            skipped.append(name)
            continue
        age_hours = max((now - created_at).total_seconds() / 3600.0, 0.0)
        if age_hours < policy.anonymous_volume_max_age_hours:
            skipped.append(name)
            continue
        delete_proc = run(["docker", "volume", "rm", name], timeout=120)
        (deleted if delete_proc.returncode == 0 else skipped).append(name)
    return {"status": "success", "deleted": deleted, "skipped": skipped}
