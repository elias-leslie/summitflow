"""Free space on one filesystem now, safest steps first, until a free-space target holds.

Steps, each only when its data lives on the target filesystem:

1. Stale agent and build temp in ``/tmp`` (``_retention_agent_tmp``).
2. ``go clean -cache`` on the owner's Go build cache.
3. ``uv cache prune`` on the owner's uv cache.
4. ``pnpm store prune`` on the owner's pnpm store.
5. Docker: stopped containers past the policy age, build cache and images at
   the pressure targets, anonymous volumes past their age.
6. Hugging Face hub repos untouched for ``HF_UNUSED_DAYS``, not open by any
   visible process and holding no mount point or other filesystem (scratch is
   mounted noatime, so mtime/ctime is the age).
7. ``/srv/scratch`` retention with the pressure age.

This is SummitFlow's emergency reclaim entry: Nightshift's space-guard runs it
(``st cleanup reclaim --filesystem PATH --target-free-gib N``) as the owner
when a disk is under its critical line; each real run is recorded as the
``emergency_reclaim`` maintenance run.

The cache roots under ``/srv/scratch/cache`` are live symlink targets (see the
README there): their tools prune inside them and the roots themselves stay.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..utils.host_retention_policy import HostRetentionPolicy
from ._retention_agent_tmp import TMP_ROOT, age_agent_tmp
from ._retention_docker import (
    prune_anonymous_docker_volumes,
    prune_builder_cache,
    prune_images,
    prune_stopped_containers,
)
from ._retention_scratch import (
    MOUNTINFO,
    SCRATCH_ROOT,
    _tree_stats,
    apply_scratch_retention,
    collect_scratch_review,
    mount_skip_reason,
    open_scratch_paths,
    remove_entry,
)

CACHE_ROOT = SCRATCH_ROOT / "cache"
UV_CACHE = CACHE_ROOT / "uv"
HF_HUB = CACHE_ROOT / "huggingface-hub"
HF_UNUSED_DAYS = 30
TOOL_TIMEOUT_SECONDS = 600

Runner = Callable[..., subprocess.CompletedProcess[str]]


def _run(args: list[str], *, env: dict[str, str] | None = None, timeout: int = TOOL_TIMEOUT_SECONDS) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False,
                          env={**os.environ, **(env or {})}, cwd=str(Path.home()))


def filesystem_source(path: Path, mountinfo: Path = Path("/proc/self/mountinfo")) -> str:
    """Mount source of ``path``; Btrfs subvolumes of one filesystem share it."""
    try:
        target = path.resolve()
        best, source = -1, str(target)
        for line in mountinfo.read_text().splitlines():
            left, _, right = line.partition(" - ")
            mount = Path(re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), left.split()[4]))
            if (target == mount or mount in target.parents) and len(mount.parts) > best:
                best, source = len(mount.parts), right.split()[1]
        return source
    except (OSError, IndexError):
        return str(path)


def free_bytes(path: Path) -> int:
    return int(shutil.disk_usage(path).free)


def _tool(name: str, args: list[str], *, run: Runner, env: dict[str, str] | None = None) -> dict[str, Any]:
    if shutil.which(args[0]) is None:
        return {"step": name, "status": "skipped", "reason": f"{args[0]} not installed"}
    try:
        proc = run(args, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"step": name, "status": "error", "error": str(exc)}
    if proc.returncode != 0:
        return {"step": name, "status": "error", "error": (proc.stderr or proc.stdout).strip()[-400:]}
    return {"step": name, "status": "success"}


def _pnpm_store(run: Runner) -> Path | None:
    if shutil.which("pnpm") is None:
        return None
    try:
        proc = run(["pnpm", "store", "path"])
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = (proc.stdout or "").strip().splitlines()
    return Path(lines[-1]) if proc.returncode == 0 and lines else None


def prune_unused_hf_repos(*, hub: Path = HF_HUB, now: datetime, max_age_days: int = HF_UNUSED_DAYS,
                          dry_run: bool = False, proc_root: Path = Path("/proc"),
                          mountinfo: Path = MOUNTINFO) -> dict[str, Any]:
    """Remove hub repos (``models--*``, ``datasets--*``) with no change in ``max_age_days``, no open file and no mount inside.

    Removal never crosses a device; a repo that changed device or identity since it was checked stays.
    """
    result: dict[str, Any] = {"step": "hf_hub", "status": "success", "deleted_paths": [], "bytes": 0, "kept": []}
    if not hub.is_dir() or hub.is_symlink():
        return {**result, "status": "skipped", "reason": "no hub cache"}
    cutoff = now.timestamp() - max_age_days * 86400
    for repo in sorted(hub.iterdir()):
        if repo.is_symlink() or not repo.is_dir() or not repo.name.startswith(("models--", "datasets--", "spaces--")):
            continue
        try:
            info = repo.lstat()
            stats = _tree_stats(repo, max_entries=200_000)
        except OSError as exc:
            result["kept"].append({"path": str(repo), "reason": exc.strerror or str(exc)})
            continue
        if stats is None or stats[0] > cutoff:
            continue
        mounted = mount_skip_reason(repo, mountinfo)
        if mounted is not None:
            result["kept"].append({"path": str(repo), "reason": mounted})
            continue
        # Fresh process scan per repo, right before removal.
        held, _ = open_scratch_paths(hub, proc_root)
        if any(target == repo or repo in target.parents for target in held):
            result["kept"].append({"path": str(repo), "reason": "in use"})
            continue
        if not dry_run:
            try:
                remove_entry(repo, (info.st_dev, info.st_ino))
            except OSError as exc:
                result.update(status="partial", error=str(exc))
                continue
        result["deleted_paths"].append(str(repo))
        result["bytes"] += stats[1]
    return result


def go_cache_dir(run: Runner) -> Path | None:
    if shutil.which("go") is None:
        return None
    try:
        proc = run(["go", "env", "GOCACHE"], timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = proc.stdout.strip() if isinstance(proc.stdout, str) else ""
    return Path(value) if proc.returncode == 0 and value.startswith("/") else None


def docker_root(run: Runner) -> Path | None:
    if shutil.which("docker") is None:
        return None
    try:
        proc = run(["docker", "info", "--format", "{{.DockerRootDir}}"], timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = proc.stdout.strip() if isinstance(proc.stdout, str) else ""
    return Path(value) if proc.returncode == 0 and value.startswith("/") else None


def _docker(policy: HostRetentionPolicy, now: datetime, run: Runner) -> dict[str, Any]:
    parts = {
        "containers": prune_stopped_containers(policy=policy, run=run),
        "builder_cache": prune_builder_cache(policy=policy, pressure_mode=True, run=run),
        "images": prune_images(policy=policy, pressure_mode=True, run=run),
        "anonymous_volumes": prune_anonymous_docker_volumes(policy=policy, now=now, run=run),
    }
    errors = [f"{name}: {part['error']}" for name, part in parts.items() if part.get("status") == "error" and part.get("error")]
    return {"step": "docker", "status": "partial" if errors else "success", "parts": parts,
            **({"error": "; ".join(errors)} if errors else {})}


def _scratch(max_age_hours: int, now: datetime, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        review = collect_scratch_review(max_age_hours=max_age_hours, now=now)
        return {"step": "scratch", "status": "would-run", "deleted_paths": [item["path"] for item in review["candidates"]],
                "bytes": sum(item["size_bytes"] for item in review["candidates"])}
    applied = apply_scratch_retention(max_age_hours=max_age_hours, now=now)
    return {"step": "scratch", "status": applied["status"], "deleted_paths": applied["deleted_paths"],
            "bytes": applied["bytes_reclaimed"], "kept": applied["kept"][:20]}


def reclaim_filesystem(
    path: Path,
    *,
    target_free_bytes: int | None = None,
    policy: HostRetentionPolicy | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
    run: Runner = _run,
) -> dict[str, Any]:
    """Run the steps on ``path``'s filesystem until ``target_free_bytes`` is free (all steps when None)."""
    effective_policy = policy or HostRetentionPolicy.from_env()
    effective_now = now or datetime.now(UTC)
    source = filesystem_source(path)
    before = free_bytes(path)
    receipt: dict[str, Any] = {"filesystem": str(path), "source": source, "target_free_bytes": target_free_bytes,
                               "free_before": before, "dry_run": dry_run, "steps": []}

    def met() -> bool:
        return target_free_bytes is not None and free_bytes(path) >= target_free_bytes

    def here(location: Path | None) -> bool:
        return location is not None and location.exists() and filesystem_source(location) == source

    pnpm_store = _pnpm_store(run)
    go_cache = go_cache_dir(run)
    docker_dir = docker_root(run)

    def pressured() -> bool:
        return not met() if target_free_bytes is not None else True

    steps: list[tuple[str, Path | None, Callable[[], dict[str, Any]]]] = [
        ("agent_tmp", TMP_ROOT, lambda: age_agent_tmp(
            agent_max_age_hours=effective_policy.agent_tmp_max_age_hours,
            build_max_age_hours=effective_policy.build_tmp_max_age_hours,
            now=effective_now, root=TMP_ROOT, pressured=pressured, dry_run=dry_run)),
        ("go_cache", go_cache, lambda: _tool("go_cache", ["go", "clean", "-cache"], run=run)),
        ("uv_cache", UV_CACHE, lambda: _tool("uv_cache", ["uv", "cache", "prune"], run=run, env={"UV_CACHE_DIR": str(UV_CACHE)})),
        ("pnpm_store", pnpm_store, lambda: _tool("pnpm_store", ["pnpm", "store", "prune"], run=run)),
        ("docker", docker_dir, lambda: _docker(effective_policy, effective_now, run)),
        ("hf_hub", HF_HUB, lambda: prune_unused_hf_repos(now=effective_now, dry_run=dry_run)),
        ("scratch", SCRATCH_ROOT, lambda: _scratch(effective_policy.scratch_pressure_max_age_hours, effective_now, dry_run)),
    ]
    for name, location, step in steps:
        if met():
            break
        if not here(location):
            receipt["steps"].append({"step": name, "status": "skipped", "reason": "not on this filesystem"})
            continue
        if dry_run and name in {"uv_cache", "pnpm_store", "go_cache", "docker"}:
            receipt["steps"].append({"step": name, "status": "would-run"})
            continue
        start = free_bytes(path)
        outcome = step()
        outcome["freed_bytes"] = max(0, free_bytes(path) - start)
        receipt["steps"].append(outcome)
    receipt["free_after"] = free_bytes(path)
    receipt["target_met"] = target_free_bytes is None or receipt["free_after"] >= target_free_bytes
    receipt["errors"] = [step.get("error") for step in receipt["steps"] if step.get("status") in {"error", "partial"} and step.get("error")]
    return receipt
