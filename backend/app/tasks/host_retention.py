"""Host artifact retention for rebuildable local data."""

from __future__ import annotations

import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from ..logging_config import get_logger
from ._retention_docker import (
    CacheResult,
    ImageResult,
    VolumeResult,
    prune_anonymous_docker_volumes,
    prune_builder_cache,
    prune_images,
)
from ._retention_fs import cleanup_old_children, collect_legacy_review_candidates
from ._retention_policy import HostRetentionPolicy

logger = get_logger(__name__)

_BYTES_PER_GB = 1024**3


class _DockerSummary(TypedDict):
    builder_cache: CacheResult
    images: ImageResult
    anonymous_volumes: VolumeResult


def _run_command(
    args: list[str],
    *,
    timeout: int,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _disk_snapshot(path: str = "/") -> dict[str, float | int | str]:
    usage = shutil.disk_usage(path)
    if hasattr(usage, "total"):
        total, used, free = int(usage.total), int(usage.used), int(usage.free)
    else:
        total, used, free = (int(part) for part in usage)
    percent_used = round((used / total) * 100, 2) if total else 0.0
    return {
        "path": path,
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "total_gb": round(total / _BYTES_PER_GB, 2),
        "used_gb": round(used / _BYTES_PER_GB, 2),
        "free_gb": round(free / _BYTES_PER_GB, 2),
        "percent_used": percent_used,
    }


def _is_pressure_mode(snapshot: dict[str, float | int | str], policy: HostRetentionPolicy) -> bool:
    percent_used = float(snapshot.get("percent_used", 0.0))
    free_gb = float(snapshot.get("free_gb", 0.0))
    return percent_used >= policy.pressure_disk_percent or free_gb <= policy.pressure_min_free_gb


def _prune_images(
    *,
    policy: HostRetentionPolicy,
    pressure_mode: bool,
) -> ImageResult:
    """Thin wrapper so tests can patch _run_command via this module's namespace."""
    return prune_images(policy=policy, pressure_mode=pressure_mode, run=_run_command)


def _docker_available() -> bool:
    return shutil.which("docker") is not None


_DOCKER_SKIPPED = _DockerSummary(
    builder_cache=CacheResult(status="skipped", reason="docker_unavailable"),
    images=ImageResult(status="skipped", reason="docker_unavailable"),
    anonymous_volumes=VolumeResult(status="skipped", deleted=[], reason="docker_unavailable"),
)


def _run_docker_cleanup(
    *,
    policy: HostRetentionPolicy,
    pressure_mode: bool,
    now: datetime,
) -> _DockerSummary:
    if not _docker_available():
        return _DOCKER_SKIPPED
    return _DockerSummary(
        builder_cache=prune_builder_cache(policy=policy, pressure_mode=pressure_mode, run=_run_command),
        images=prune_images(policy=policy, pressure_mode=pressure_mode, run=_run_command),
        anonymous_volumes=prune_anonymous_docker_volumes(policy=policy, now=now, run=_run_command),
    )


def cleanup_host_artifacts(
    *,
    home_dir: Path | None = None,
    now: datetime | None = None,
    policy: HostRetentionPolicy | None = None,
) -> dict[str, object]:
    """Prune rebuildable host artifacts and report larger review candidates."""
    effective_policy = policy or HostRetentionPolicy.from_env()
    effective_now = now or datetime.now(UTC)
    effective_home = home_dir or Path.home()

    before = _disk_snapshot("/")
    pressure_mode = _is_pressure_mode(before, effective_policy)

    npx_result = cleanup_old_children(
        effective_home / ".npm" / "_npx",
        max_age_hours=effective_policy.npx_max_age_hours,
        now=effective_now,
    )
    playwright_result = cleanup_old_children(
        effective_home / ".cache" / "ms-playwright",
        max_age_hours=effective_policy.playwright_max_age_hours,
        now=effective_now,
    )
    tool_cache_deleted = npx_result["deleted_paths"] + playwright_result["deleted_paths"]
    tool_cache_reclaimed = npx_result["bytes_reclaimed"] + playwright_result["bytes_reclaimed"]

    docker = _run_docker_cleanup(policy=effective_policy, pressure_mode=pressure_mode, now=effective_now)

    after = _disk_snapshot("/")
    bytes_reclaimed = max(int(after["free_bytes"]) - int(before["free_bytes"]), 0)
    review_candidates = collect_legacy_review_candidates(
        effective_home,
        max_age_hours=effective_policy.legacy_report_max_age_hours,
        now=effective_now,
    )

    errors = [
        entry["error"]
        for entry in (docker["builder_cache"], docker["images"], docker["anonymous_volumes"])
        if isinstance(entry, dict) and entry.get("status") == "error" and entry.get("error")
    ]
    status = "partial" if errors else "success"
    items_deleted = tool_cache_deleted + len(docker["anonymous_volumes"].get("deleted", []))

    summary: dict[str, object] = {
        "status": status,
        "pressure_mode": pressure_mode,
        "items_deleted": items_deleted,
        "bytes_reclaimed": bytes_reclaimed,
        "bytes_reclaimed_from_path_cleanup": tool_cache_reclaimed,
        "disk_before": before,
        "disk_after": after,
        "tool_caches": {
            "deleted_paths": tool_cache_deleted,
            "bytes_reclaimed": tool_cache_reclaimed,
            "npx": npx_result,
            "playwright": playwright_result,
        },
        "docker_builder_cache": docker["builder_cache"],
        "docker_images": docker["images"],
        "docker_anonymous_volumes": docker["anonymous_volumes"],
        "review_candidates": review_candidates,
        "errors": errors,
    }
    logger.info(
        "host_retention_completed",
        status=status,
        pressure_mode=pressure_mode,
        items_deleted=items_deleted,
        bytes_reclaimed=bytes_reclaimed,
        review_candidates=len(review_candidates),
    )
    return summary


__all__ = ["HostRetentionPolicy", "cleanup_host_artifacts"]
