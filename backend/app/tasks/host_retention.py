"""Host artifact retention for rebuildable local data."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

from ..logging_config import get_logger
from ._retention_docker import (
    CacheResult,
    ImageResult,
    VolumeResult,
    prune_anonymous_docker_volumes,
    prune_builder_cache,
    prune_images,
)
from ._retention_fs import (
    cleanup_old_children,
    cleanup_stale_hermes_checkpoints,
    cleanup_tmp_backups,
    collect_legacy_review_candidates,
)
from ._retention_policy import HostRetentionPolicy

logger = get_logger(__name__)

_BYTES_PER_GB = 1024**3


class VeeamSnapshotResult(TypedDict, total=False):
    status: str
    deleted: list[str]
    skipped: list[str]
    max_age_hours: int
    reason: str
    error: str


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



def _active_veeam_session(run: Any = _run_command) -> tuple[bool | None, str | None]:
    proc = run(["sudo", "-n", "veeamconfig", "session", "list"], timeout=30)
    if proc.returncode != 0:
        return None, _tail_output(proc.stderr or proc.stdout)
    for line in proc.stdout.splitlines():
        parts = [part.strip() for part in re.split(r"\s{2,}", line.strip()) if part.strip()]
        if any(part in {"Running", "Pending"} for part in parts):
            return True, None
    return False, None


def _tail_output(text: str, *, limit: int = 400) -> str:
    return text.strip()[-limit:] if text else ""


def _root_btrfs_source(run: Any = _run_command) -> str | None:
    proc = run(["findmnt", "-no", "SOURCE,FSTYPE", "/"], timeout=15)
    if proc.returncode != 0:
        return None
    parts = proc.stdout.split()
    if len(parts) < 2 or parts[-1] != "btrfs":
        return None
    return " ".join(parts[:-1]).split("[", 1)[0]


def _btrfs_subvolume_paths(mount_point: Path, run: Any = _run_command) -> list[str]:
    proc = run(["sudo", "-n", "btrfs", "subvolume", "list", str(mount_point)], timeout=60)
    if proc.returncode != 0:
        return []
    paths = []
    for line in proc.stdout.splitlines():
        _, marker, path = line.partition(" path ")
        if marker and path:
            paths.append(path.strip())
    return paths


def cleanup_stale_veeam_snapshots(
    *,
    policy: HostRetentionPolicy,
    now: datetime,
    run: Any = _run_command,
    mount_point: Path | None = None,
) -> VeeamSnapshotResult:
    """Delete stale Veeam btrfs temp snapshots that pin freed disk blocks."""
    active, reason = _active_veeam_session(run)
    if active is True:
        return {"status": "skipped", "reason": "veeam_session_active", "deleted": [], "skipped": []}
    if active is None:
        return {"status": "skipped", "reason": reason or "veeam_status_unavailable", "deleted": [], "skipped": []}

    mounted_here = False
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if mount_point is None:
        source = _root_btrfs_source(run)
        if not source:
            return {"status": "skipped", "reason": "root_not_btrfs", "deleted": [], "skipped": []}
        temp_dir = tempfile.TemporaryDirectory(prefix="summitflow-btrfs-top-")
        mount_point = Path(temp_dir.name)
        proc = run(["sudo", "-n", "mount", "-o", "subvolid=5", source, str(mount_point)], timeout=60)
        if proc.returncode != 0:
            temp_dir.cleanup()
            return {
                "status": "skipped",
                "reason": "top_level_mount_failed",
                "error": _tail_output(proc.stderr or proc.stdout),
                "deleted": [],
                "skipped": [],
            }
        mounted_here = True

    deleted: list[str] = []
    skipped: list[str] = []
    try:
        snapshots_root = mount_point / ".veeam_snapshots"
        if not snapshots_root.is_dir():
            return {"status": "success", "deleted": [], "skipped": [], "max_age_hours": policy.veeam_snapshot_max_age_hours}

        subvolume_paths = _btrfs_subvolume_paths(mount_point, run)
        for snapshot_dir in sorted(path for path in snapshots_root.iterdir() if path.is_dir()):
            if (now.timestamp() - snapshot_dir.stat().st_mtime) / 3600.0 < policy.veeam_snapshot_max_age_hours:
                skipped.append(str(snapshot_dir))
                continue
            prefix = f".veeam_snapshots/{snapshot_dir.name}/"
            children = sorted(
                (path for path in subvolume_paths if path.startswith(prefix)),
                key=lambda path: path.count("/"),
                reverse=True,
            )
            failed = False
            for child in children:
                proc = run(["sudo", "-n", "btrfs", "subvolume", "delete", str(mount_point / child)], timeout=300)
                if proc.returncode != 0:
                    failed = True
                    break
            if failed:
                skipped.append(str(snapshot_dir))
                continue
            run(["sudo", "-n", "rmdir", str(snapshot_dir)], timeout=30)
            deleted.append(str(snapshot_dir))

        if deleted:
            run(["sudo", "-n", "btrfs", "subvolume", "sync", str(mount_point)], timeout=600)
        return {
            "status": "success",
            "deleted": deleted,
            "skipped": skipped,
            "max_age_hours": policy.veeam_snapshot_max_age_hours,
        }
    finally:
        if mounted_here and mount_point is not None:
            run(["sudo", "-n", "umount", str(mount_point)], timeout=60)
        if temp_dir is not None:
            temp_dir.cleanup()


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
    tmp_dir: Path | None = None,
    now: datetime | None = None,
    policy: HostRetentionPolicy | None = None,
) -> dict[str, object]:
    """Prune rebuildable host artifacts and report larger review candidates."""
    effective_policy = policy or HostRetentionPolicy.from_env()
    effective_now = now or datetime.now(UTC)
    effective_home = home_dir or Path.home()
    effective_tmp = tmp_dir or Path("/tmp")

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
    tmp_backups_result = cleanup_tmp_backups(
        effective_tmp,
        max_age_hours=effective_policy.tmp_backup_max_age_hours,
        now=effective_now,
    )
    hermes_checkpoints_result = cleanup_stale_hermes_checkpoints(
        effective_home / ".hermes",
        tmp_workdir_max_age_hours=effective_policy.hermes_checkpoint_tmp_max_age_hours,
        internal_workdir_max_age_hours=effective_policy.hermes_checkpoint_internal_max_age_hours,
        now=effective_now,
    )
    tool_cache_deleted = (
        npx_result["deleted_paths"]
        + playwright_result["deleted_paths"]
        + tmp_backups_result["deleted_paths"]
        + hermes_checkpoints_result["deleted_paths"]
    )
    tool_cache_reclaimed = (
        npx_result["bytes_reclaimed"]
        + playwright_result["bytes_reclaimed"]
        + tmp_backups_result["bytes_reclaimed"]
        + hermes_checkpoints_result["bytes_reclaimed"]
    )

    docker = _run_docker_cleanup(policy=effective_policy, pressure_mode=pressure_mode, now=effective_now)
    veeam_snapshots = cleanup_stale_veeam_snapshots(policy=effective_policy, now=effective_now)

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
        "temp_backups": tmp_backups_result,
        "hermes_checkpoints": hermes_checkpoints_result,
        "docker_builder_cache": docker["builder_cache"],
        "docker_images": docker["images"],
        "docker_anonymous_volumes": docker["anonymous_volumes"],
        "veeam_snapshots": veeam_snapshots,
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
