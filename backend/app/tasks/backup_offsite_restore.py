"""Restore from the Google Drive repository by project or path, the way agents and ``st backup restore`` do it.

The daily job stores the host snapshots at their real paths and tags each snapshot with ``project:<name>``,
so a project comes back with ``restic restore <snapshot> --include /srv/workspaces/projects/<name>``.
Restores always land in a directory the caller names (never over the live path) and are read back with
restic's ``--verify``.
"""

from __future__ import annotations

import dataclasses
import re
import subprocess
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from ..utils.shared_paths import get_workspaces_root
from .backup_database import POSTGRES_DUMP_NAME, REDIS_DUMP_NAME
from .backup_offsite import (
    SUBVOLUME_JOBS,
    TAG,
    OffsiteError,
    Repo,
    _env,
    _restic_args,
    load_target,
    prepare_runtime,
)

_NAME = re.compile(r"[A-Za-z0-9._-]+")
STREAM_FILES = {"postgres": POSTGRES_DUMP_NAME, "redis": REDIS_DUMP_NAME}
RESTORE_TIMEOUT_SECONDS = 4 * 3600


def open_repo() -> Repo:
    target = load_target()
    return Repo(target, prepare_runtime(target))


def _job_for(path: str) -> str:
    for name, spec in SUBVOLUME_JOBS.items():
        if any(path == item or path.startswith(item.rstrip("/") + "/") for item in spec["paths"]):
            return name
    raise OffsiteError(f"{path} is not part of the Google Drive backup (it is under no backed-up location)")


def resolve(selector: str) -> dict[str, str]:
    """A project name, a stream name (``postgres``, ``redis``) or an absolute path -> the job, path and tag to look for."""
    if selector in STREAM_FILES:
        return {"job": selector, "path": "/" + STREAM_FILES[selector], "kind": "stream"}
    if selector.startswith("/"):
        path = str(Path(selector))
        job = _job_for(path)
        return {"job": job, "path": path, "kind": "path"}
    if not _NAME.fullmatch(selector):
        raise OffsiteError(f"{selector!r} is not a project name, postgres, redis or an absolute path")
    path = str(get_workspaces_root() / "projects" / selector)
    return {"job": "workspaces", "path": path, "kind": "project", "tag": f"project:{selector}"}


def snapshots(selector: str | None = None, *, limit: int = 20, repo: Repo | None = None) -> list[dict[str, Any]]:
    """Newest first. Without a selector, the latest snapshot of every job."""
    repo = repo or open_repo()
    args = ["snapshots", "--host", repo.target.hostname]
    if selector:
        wanted = resolve(selector)
        args += ["--tag", ",".join([TAG, f"job:{wanted['job']}", *([wanted["tag"]] if wanted.get("tag") else [])])]
    else:
        args += ["--tag", TAG]
    found = repo.json(*args, timeout=3600)
    rows = [{"id": item["short_id"], "full_id": item["id"], "time": item["time"], "paths": item.get("paths"),
             "job": next((t[4:] for t in item.get("tags") or [] if t.startswith("job:")), None),
             "btrbk_run": next((t[6:] for t in item.get("tags") or [] if t.startswith("btrbk:")), None)} for item in found]
    rows.sort(key=lambda row: row["time"], reverse=True)
    return rows[:limit]


def _pick(rows: Sequence[dict[str, Any]], snapshot: str | None, at: datetime | None) -> dict[str, Any]:
    if snapshot:
        match = next((row for row in rows if snapshot in {row["id"], row["full_id"]} or row["full_id"].startswith(snapshot)), None)
    elif at is not None:
        match = next((row for row in rows if datetime.fromisoformat(row["time"]) <= at), None)
    else:
        match = rows[0] if rows else None
    if match is None:
        raise OffsiteError("No Google Drive snapshot matches" + (f" {snapshot}" if snapshot else " that project or time"))
    return match


def restore(selector: str, target: Path, *, snapshot: str | None = None, at: datetime | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Restore one project, path or database dump from Google Drive into ``target`` (an empty or new directory)."""
    repo = open_repo()
    wanted = resolve(selector)
    chosen = _pick(snapshots(selector, limit=1000, repo=repo), snapshot, at)
    result: dict[str, Any] = {"selector": selector, "snapshot": chosen["id"], "snapshot_time": chosen["time"], "path": wanted["path"],
                              "target": str(target), "dry_run": dry_run}
    if dry_run:
        return result
    target = target.resolve()
    if target.exists() and any(target.iterdir()):
        raise OffsiteError(f"{target} is not empty; restore into a new or empty directory")
    target.mkdir(parents=True, exist_ok=True)
    if wanted["kind"] == "stream":
        command = _restic_args(repo.target, repo.runtime, "dump", chosen["full_id"], wanted["path"])
        out = target / Path(wanted["path"]).name
        with out.open("wb") as stream:
            proc = subprocess.run(command, stdout=stream, stderr=subprocess.PIPE, env=_env(repo.target, repo.runtime, root=False), timeout=RESTORE_TIMEOUT_SECONDS, check=False)
        if proc.returncode:
            raise OffsiteError(f"restic dump failed: {proc.stderr.decode(errors='replace')[-300:]}")
        result.update(restored=str(out), bytes=out.stat().st_size)
        return result
    outcome = repo.restic("restore", chosen["full_id"], "--target", str(target), "--include", wanted["path"], "--verify", timeout=RESTORE_TIMEOUT_SECONDS)
    if not outcome.ok:
        raise OffsiteError(f"restic restore failed: {outcome.stderr[-300:]}")
    restored = target / wanted["path"].lstrip("/")
    if not restored.exists():
        raise OffsiteError(f"The snapshot has nothing at {wanted['path']}")
    result.update(restored=str(restored))
    return result


# ---- snapshots made before the daily job (per-project sources, staged payloads) ------------------------------------
# Read-only: they age out of the Drive repository on their own and the T7 repository is no longer written to.

def _legacy_repo(which: str) -> Repo:
    base = load_target()
    if which == "drive":
        return Repo(base, prepare_runtime(base))
    if which != "local" or base.local_repository is None or base.local_password_file is None:
        raise OffsiteError("Pick the old backups on 'drive' or 'local' (the T7 restic repository)")
    local = dataclasses.replace(base, repository=str(base.local_repository), password_file=base.local_password_file, rclone_config=None)
    return Repo(local, prepare_runtime(base))


def legacy_snapshots(source: str | None = None, *, where: str = "drive", limit: int = 30) -> list[dict[str, Any]]:
    """Old per-source snapshots, newest first (tag ``source:<id>``, never the daily job's ``offsite`` tag)."""
    repo = _legacy_repo(where)
    args = ["snapshots", "--host", repo.target.hostname]
    if source:
        args += ["--tag", f"source:{source}"]
    found = [item for item in repo.json(*args, timeout=3600) if TAG not in (item.get("tags") or [])]
    rows = [{"id": item["short_id"], "full_id": item["id"], "time": item["time"],
             "source": next((t[7:] for t in item.get("tags") or [] if t.startswith("source:")), None)} for item in found]
    rows.sort(key=lambda row: row["time"], reverse=True)
    return rows[:limit]


def restore_legacy(snapshot: str, target: Path, *, where: str = "drive", include: str | None = None) -> dict[str, Any]:
    """Restore an old snapshot as it was stored into a new or empty directory; ``include`` limits it to one path inside."""
    repo = _legacy_repo(where)
    target = target.resolve()
    if target.exists() and any(target.iterdir()):
        raise OffsiteError(f"{target} is not empty; restore into a new or empty directory")
    target.mkdir(parents=True, exist_ok=True)
    args = ["restore", snapshot, "--target", str(target), "--verify"]
    if include:
        args += ["--include", include]
    outcome = repo.restic(*args, timeout=RESTORE_TIMEOUT_SECONDS)
    if not outcome.ok:
        raise OffsiteError(f"restic restore failed: {outcome.stderr[-300:]}")
    return {"snapshot": snapshot, "where": where, "target": str(target), "include": include}
