"""Host artifact retention for rebuildable local data."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..logging_config import get_logger

logger = get_logger(__name__)

_BYTES_PER_GB = 1024**3
_ANON_DOCKER_VOLUME_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class HostRetentionPolicy:
    """Safe retention policy for rebuildable host artifacts."""

    pressure_disk_percent: float = 75.0
    pressure_min_free_gb: float = 25.0
    builder_cache_target_gb: int = 2
    builder_cache_pressure_target_gb: int = 1
    image_max_age_hours: int = 0
    image_pressure_max_age_hours: int = 0
    anonymous_volume_max_age_hours: int = 7 * 24
    npx_max_age_hours: int = 7 * 24
    playwright_max_age_hours: int = 14 * 24
    legacy_report_max_age_hours: int = 3 * 24

    @classmethod
    def from_env(cls) -> HostRetentionPolicy:
        def _float_env(name: str, default: float) -> float:
            raw = os.environ.get(name)
            if raw is None:
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        def _int_env(name: str, default: int) -> int:
            raw = os.environ.get(name)
            if raw is None:
                return default
            try:
                return int(raw)
            except ValueError:
                return default

        return cls(
            pressure_disk_percent=_float_env("SF_HOST_RETENTION_PRESSURE_DISK_PERCENT", 75.0),
            pressure_min_free_gb=_float_env("SF_HOST_RETENTION_PRESSURE_MIN_FREE_GB", 25.0),
            builder_cache_target_gb=_int_env("SF_HOST_RETENTION_BUILDER_CACHE_TARGET_GB", 2),
            builder_cache_pressure_target_gb=_int_env(
                "SF_HOST_RETENTION_BUILDER_CACHE_PRESSURE_TARGET_GB", 1
            ),
            image_max_age_hours=_int_env("SF_HOST_RETENTION_IMAGE_MAX_AGE_HOURS", 0),
            image_pressure_max_age_hours=_int_env(
                "SF_HOST_RETENTION_IMAGE_PRESSURE_MAX_AGE_HOURS", 0
            ),
            anonymous_volume_max_age_hours=_int_env(
                "SF_HOST_RETENTION_ANON_VOLUME_MAX_AGE_HOURS", 7 * 24
            ),
            npx_max_age_hours=_int_env("SF_HOST_RETENTION_NPX_MAX_AGE_HOURS", 7 * 24),
            playwright_max_age_hours=_int_env(
                "SF_HOST_RETENTION_PLAYWRIGHT_MAX_AGE_HOURS", 14 * 24
            ),
            legacy_report_max_age_hours=_int_env(
                "SF_HOST_RETENTION_LEGACY_REPORT_MAX_AGE_HOURS", 3 * 24
            ),
        )


def _disk_snapshot(path: str = "/") -> dict[str, float | int | str]:
    usage = shutil.disk_usage(path)
    if hasattr(usage, "total"):
        total = int(usage.total)
        used = int(usage.used)
        free = int(usage.free)
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


def _tail(text: str, *, limit: int = 400) -> str:
    return text.strip()[-limit:] if text else ""


def _path_size_bytes(path: Path) -> int:
    try:
        if path.is_symlink() or path.is_file():
            return int(path.lstat().st_size)
    except OSError:
        return 0

    total = 0
    for root, dirs, files in os.walk(path, followlinks=False):
        root_path = Path(root)
        for name in dirs:
            dir_path = root_path / name
            try:
                if dir_path.is_symlink():
                    total += int(dir_path.lstat().st_size)
            except OSError:
                continue
        for name in files:
            file_path = root_path / name
            try:
                total += int(file_path.lstat().st_size)
            except OSError:
                continue
    return total


def _delete_path(path: Path) -> int:
    reclaimed = _path_size_bytes(path)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            return 0
    return reclaimed


def _age_hours(path: Path, *, now: datetime) -> float:
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except OSError:
        return 0.0
    return max((now - modified).total_seconds() / 3600.0, 0.0)


def _cleanup_old_children(
    root: Path,
    *,
    max_age_hours: int,
    now: datetime,
) -> dict[str, Any]:
    if not root.is_dir():
        return {"deleted_paths": 0, "bytes_reclaimed": 0, "deleted": []}

    deleted: list[str] = []
    reclaimed = 0
    for child in root.iterdir():
        if _age_hours(child, now=now) < max_age_hours:
            continue
        reclaimed += _delete_path(child)
        deleted.append(str(child))
    return {
        "deleted_paths": len(deleted),
        "bytes_reclaimed": reclaimed,
        "deleted": deleted,
    }


def _collect_legacy_review_candidates(
    home_dir: Path,
    *,
    max_age_hours: int,
    now: datetime,
) -> list[dict[str, Any]]:
    root = home_dir / "_legacy-project-roots"
    if not root.is_dir():
        return []

    candidates: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        age_hours = _age_hours(child, now=now)
        if age_hours < max_age_hours:
            continue
        candidates.append(
            {
                "path": str(child),
                "reason": "legacy_project_root",
                "age_hours": round(age_hours, 1),
                "size_bytes": _path_size_bytes(child),
                "action": "review_only",
            }
        )
    return candidates


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _prune_builder_cache(
    *,
    policy: HostRetentionPolicy,
    pressure_mode: bool,
) -> dict[str, Any]:
    target_gb = (
        policy.builder_cache_pressure_target_gb
        if pressure_mode
        else policy.builder_cache_target_gb
    )
    proc = _run_command(
        [
            "docker",
            "builder",
            "prune",
            "--force",
            "--all",
            "--max-used-space",
            f"{target_gb}gb",
        ],
        timeout=300,
    )
    if proc.returncode != 0:
        return {
            "status": "error",
            "target_gb": target_gb,
            "error": _tail(proc.stderr or proc.stdout),
        }
    return {"status": "success", "target_gb": target_gb, "stdout_tail": _tail(proc.stdout)}


def _prune_images(
    *,
    policy: HostRetentionPolicy,
    pressure_mode: bool,
) -> dict[str, Any]:
    max_age_hours = (
        policy.image_pressure_max_age_hours
        if pressure_mode
        else policy.image_max_age_hours
    )
    args = [
        "docker",
        "image",
        "prune",
        "--force",
        "--all",
    ]
    if max_age_hours > 0:
        args.extend(["--filter", f"until={max_age_hours}h"])
    proc = _run_command(args, timeout=300)
    if proc.returncode != 0:
        return {
            "status": "error",
            "max_age_hours": max_age_hours,
            "error": _tail(proc.stderr or proc.stdout),
        }
    return {
        "status": "success",
        "max_age_hours": max_age_hours,
        "stdout_tail": _tail(proc.stdout),
    }


def _inspect_volume_created_at(name: str) -> datetime | None:
    proc = _run_command(["docker", "volume", "inspect", name], timeout=60)
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


def _prune_anonymous_docker_volumes(
    *,
    policy: HostRetentionPolicy,
    now: datetime,
) -> dict[str, Any]:
    proc = _run_command(["docker", "volume", "ls", "-q", "-f", "dangling=true"], timeout=60)
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
        created_at = _inspect_volume_created_at(name)
        if created_at is None:
            skipped.append(name)
            continue
        age_hours = max((now - created_at).total_seconds() / 3600.0, 0.0)
        if age_hours < policy.anonymous_volume_max_age_hours:
            skipped.append(name)
            continue
        delete_proc = _run_command(["docker", "volume", "rm", name], timeout=120)
        if delete_proc.returncode == 0:
            deleted.append(name)
        else:
            skipped.append(name)
    return {"status": "success", "deleted": deleted, "skipped": skipped}


def cleanup_host_artifacts(
    *,
    home_dir: Path | None = None,
    now: datetime | None = None,
    policy: HostRetentionPolicy | None = None,
) -> dict[str, Any]:
    """Prune rebuildable host artifacts and report larger review candidates."""
    effective_policy = policy or HostRetentionPolicy.from_env()
    effective_now = now or datetime.now(UTC)
    effective_home = home_dir or Path.home()

    before = _disk_snapshot("/")
    pressure_mode = _is_pressure_mode(before, effective_policy)

    tool_caches = {
        "npx": _cleanup_old_children(
            effective_home / ".npm" / "_npx",
            max_age_hours=effective_policy.npx_max_age_hours,
            now=effective_now,
        ),
        "playwright": _cleanup_old_children(
            effective_home / ".cache" / "ms-playwright",
            max_age_hours=effective_policy.playwright_max_age_hours,
            now=effective_now,
        ),
    }
    tool_cache_deleted = sum(int(entry["deleted_paths"]) for entry in tool_caches.values())
    tool_cache_reclaimed = sum(int(entry["bytes_reclaimed"]) for entry in tool_caches.values())

    docker_summary: dict[str, Any]
    if _docker_available():
        docker_summary = {
            "builder_cache": _prune_builder_cache(
                policy=effective_policy,
                pressure_mode=pressure_mode,
            ),
            "images": _prune_images(
                policy=effective_policy,
                pressure_mode=pressure_mode,
            ),
            "anonymous_volumes": _prune_anonymous_docker_volumes(
                policy=effective_policy,
                now=effective_now,
            ),
        }
    else:
        docker_summary = {
            "builder_cache": {"status": "skipped", "reason": "docker_unavailable"},
            "images": {"status": "skipped", "reason": "docker_unavailable"},
            "anonymous_volumes": {"status": "skipped", "deleted": [], "reason": "docker_unavailable"},
        }

    after = _disk_snapshot("/")
    bytes_reclaimed = max(int(after["free_bytes"]) - int(before["free_bytes"]), 0)
    review_candidates = _collect_legacy_review_candidates(
        effective_home,
        max_age_hours=effective_policy.legacy_report_max_age_hours,
        now=effective_now,
    )

    errors = [
        entry["error"]
        for entry in (
            docker_summary["builder_cache"],
            docker_summary["images"],
            docker_summary["anonymous_volumes"],
        )
        if isinstance(entry, dict) and entry.get("status") == "error" and entry.get("error")
    ]
    status = "partial" if errors else "success"
    items_deleted = (
        tool_cache_deleted
        + len(docker_summary["anonymous_volumes"].get("deleted", []))
    )

    summary = {
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
            "npx": tool_caches["npx"],
            "playwright": tool_caches["playwright"],
        },
        "docker_builder_cache": docker_summary["builder_cache"],
        "docker_images": docker_summary["images"],
        "docker_anonymous_volumes": docker_summary["anonymous_volumes"],
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
