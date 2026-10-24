"""Host artifact retention for rebuildable local data."""

from __future__ import annotations

import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from ._retention_agent_tmp import age_agent_tmp
from ._retention_check_artifacts import prune_check_artifacts
from ._retention_fs import (
    cleanup_old_children,
    cleanup_stale_hermes_checkpoints,
    cleanup_tmp_backups,
    collect_legacy_review_candidates,
    playwright_required_children,
)
from ._retention_policy import HostRetentionPolicy
from ._retention_reclaim import (
    UV_CACHE,
    _run,
    _tool,
    filesystem_source,
    go_cache_dir,
    reclaim_filesystem,
)
from ._retention_scratch import SCRATCH_ROOT, weekly_scratch_retention

logger = get_logger(__name__)

_BYTES_PER_GB = 1024**3


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


def _go_cache_over_limit(policy: HostRetentionPolicy) -> dict[str, object]:
    """Clear Go's build cache once it is larger than the policy limit."""
    def run(args: list[str], *, timeout: int = 600, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return _run_command(args, timeout=timeout)

    cache = go_cache_dir(run)
    if cache is None or not cache.is_dir():
        return {"status": "skipped", "reason": "no go build cache"}
    try:
        from ._retention_scratch import _tree_stats

        stats = _tree_stats(cache, max_entries=2_000_000)
    except OSError as exc:
        return {"status": "error", "error": str(exc)}
    size = stats[1] if stats else None
    limit = int(policy.go_cache_max_gb * _BYTES_PER_GB)
    if size is not None and size <= limit:
        return {"status": "kept", "size_bytes": size, "limit_bytes": limit}
    proc = run(["go", "clean", "-cache"])
    if proc.returncode != 0:
        return {"status": "error", "error": (proc.stderr or proc.stdout).strip()[-400:]}
    return {"status": "success", "size_bytes": size, "limit_bytes": limit}


def _uv_cache_prune() -> dict[str, object]:
    """Daily `uv cache prune` (unused entries only) on the owner's uv cache; Nightshift's housekeeping no longer does it."""
    if not UV_CACHE.is_dir():
        return {"status": "skipped", "reason": "no uv cache"}
    result = _tool("uv_cache", ["uv", "cache", "prune"], run=_run, env={"UV_CACHE_DIR": str(UV_CACHE)})
    return {key: value for key, value in result.items() if key != "step"}


def _prune_project_check_artifacts(
    roots: list[Path] | None, policy: HostRetentionPolicy, now: datetime,
) -> dict[str, object]:
    deleted = reclaimed = 0
    try:
        if roots is None:
            from ..storage.projects import list_projects

            roots = [Path(str(row["root_path"])) for row in list_projects() if row.get("root_path")]
        for root in roots:
            if not root.is_dir():
                continue
            try:
                result = prune_check_artifacts(
                    root, now=now, details_max_age_hours=policy.check_details_max_age_hours,
                    stages_max_age_hours=policy.check_stages_max_age_hours,
                    observations_max_age_hours=policy.check_observations_max_age_hours,
                    observations_keep=policy.check_observations_keep,
                )
            except OSError as exc:
                logger.warning("check_artifact_retention_failed", root=str(root), error=str(exc))
                continue
            deleted += result["deleted_paths"]
            reclaimed += result["bytes_reclaimed"]
    except Exception as exc:  # one step must not abort host retention
        logger.warning("check_artifact_retention_failed", error=str(exc))
        return {"status": "error", "error": str(exc), "deleted_paths": deleted, "bytes_reclaimed": reclaimed}
    return {"status": "success", "deleted_paths": deleted, "bytes_reclaimed": reclaimed}


def cleanup_host_artifacts(
    *,
    home_dir: Path | None = None,
    tmp_dir: Path | None = None,
    now: datetime | None = None,
    policy: HostRetentionPolicy | None = None,
    project_roots: list[Path] | None = None,
) -> dict[str, object]:
    """Prune rebuildable host artifacts and report larger review candidates."""
    effective_policy = policy or HostRetentionPolicy.from_env()
    effective_now = now or datetime.now(UTC)
    effective_home = home_dir or Path.home()
    effective_tmp = tmp_dir or Path("/tmp")

    # Pressure is per filesystem this step cleans: "/" (tool caches, Docker)
    # and the scratch filesystem (shared with /srv/workspaces on this host).
    before = _disk_snapshot("/")
    root_pressure = _is_pressure_mode(before, effective_policy)
    scratch_before: dict[str, float | int | str] | None = None
    if SCRATCH_ROOT.is_dir() and filesystem_source(SCRATCH_ROOT) != filesystem_source(Path("/")):
        scratch_before = _disk_snapshot(str(SCRATCH_ROOT))
    scratch_pressure = SCRATCH_ROOT.is_dir() and _is_pressure_mode(scratch_before or before, effective_policy)
    pressure_mode = root_pressure or scratch_pressure

    npx_result = cleanup_old_children(
        effective_home / ".npm" / "_npx",
        max_age_hours=effective_policy.npx_max_age_hours,
        now=effective_now,
    )
    playwright_root = effective_home / ".cache" / "ms-playwright"
    playwright_result = cleanup_old_children(
        playwright_root,
        max_age_hours=effective_policy.playwright_max_age_hours,
        now=effective_now,
        protected=playwright_required_children(playwright_root),
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
    agent_tmp_result: dict[str, Any]
    try:
        agent_tmp_result = age_agent_tmp(
            agent_max_age_hours=effective_policy.agent_tmp_max_age_hours,
            build_max_age_hours=effective_policy.build_tmp_max_age_hours,
            now=effective_now, root=effective_tmp,
        )
    except Exception as exc:  # one step must not abort host retention
        logger.warning("agent_tmp_retention_failed", error=str(exc))
        agent_tmp_result = {"status": "error", "error": str(exc), "deleted_paths": [], "bytes": 0}
    go_cache_result = _go_cache_over_limit(effective_policy)
    uv_cache_result = _uv_cache_prune()
    agent_tmp_removed: list[str] = list(agent_tmp_result.get("deleted_paths") or [])
    agent_tmp_bytes = int(agent_tmp_result.get("bytes") or 0)
    tool_cache_deleted = (
        len(agent_tmp_removed)
        + npx_result["deleted_paths"]
        + playwright_result["deleted_paths"]
        + tmp_backups_result["deleted_paths"]
        + hermes_checkpoints_result["deleted_paths"]
    )
    tool_cache_reclaimed = (
        agent_tmp_bytes
        + npx_result["bytes_reclaimed"]
        + playwright_result["bytes_reclaimed"]
        + tmp_backups_result["bytes_reclaimed"]
        + hermes_checkpoints_result["bytes_reclaimed"]
    )

    reclaim: dict[str, Any] | None = None
    try:
        if scratch_pressure:
            # Do not wait for the weekly cadence: owner-tool cache prunes, then
            # scratch retention at the pressure age, on the scratch filesystem.
            reclaim = reclaim_filesystem(SCRATCH_ROOT, policy=effective_policy, now=effective_now)
            step = next((item for item in reclaim["steps"] if item["step"] == "scratch"), {})
            scratch_result: dict[str, Any] = {"status": step.get("status", "skipped"), "trigger": "pressure",
                                              "deleted_paths": step.get("deleted_paths") or [],
                                              "bytes_reclaimed": step.get("bytes", 0), **({"error": step["error"]} if step.get("error") else {})}
        else:
            scratch_result = weekly_scratch_retention(
                max_age_hours=effective_policy.scratch_review_max_age_hours, now=effective_now,
            )
    except Exception as exc:  # one step must not abort host retention
        logger.warning("scratch_retention_failed", error=str(exc))
        scratch_result = {"status": "error", "error": str(exc)}
    check_artifacts = _prune_project_check_artifacts(project_roots, effective_policy, effective_now)

    after = _disk_snapshot("/")
    bytes_reclaimed = max(int(after["free_bytes"]) - int(before["free_bytes"]), 0)
    review_candidates = collect_legacy_review_candidates(
        effective_home,
        max_age_hours=effective_policy.legacy_report_max_age_hours,
        now=effective_now,
    )

    errors = [
        entry["error"]
        for entry in (scratch_result, check_artifacts, agent_tmp_result, go_cache_result, uv_cache_result)
        if isinstance(entry, dict) and entry.get("status") == "error" and entry.get("error")
    ]
    status = "partial" if errors else "success"
    items_deleted = tool_cache_deleted + len(scratch_result.get("deleted_paths") or [])

    summary: dict[str, object] = {
        "status": status,
        "pressure_mode": pressure_mode,
        "pressure_filesystems": [snapshot["path"] for snapshot, pressured in ((before, root_pressure), (scratch_before, scratch_pressure)) if snapshot and pressured],
        "items_deleted": items_deleted,
        "bytes_reclaimed": bytes_reclaimed,
        "bytes_reclaimed_from_path_cleanup": tool_cache_reclaimed,
        "disk_before": before,
        "disk_after": after,
        "scratch_disk_before": scratch_before,
        "scratch_reclaim": reclaim,
        "tool_caches": {
            "deleted_paths": tool_cache_deleted,
            "bytes_reclaimed": tool_cache_reclaimed,
            "npx": npx_result,
            "playwright": playwright_result,
        },
        "agent_tmp": agent_tmp_result,
        "go_cache": go_cache_result,
        "uv_cache": uv_cache_result,
        "temp_backups": tmp_backups_result,
        "scratch": scratch_result,
        "check_artifacts": check_artifacts,
        "hermes_checkpoints": hermes_checkpoints_result,
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
