"""Weekly read-back of the Google Drive copy, kept apart from the backup.

The daily copy must never wait on Drive, whose per-file API is slow, so proving that what is stored can
be read lives here: ``summitflow-host-verify.timer`` runs this at low priority, outside the backup unit
and the heavy-work lane. Every step has a wall-clock bound. Running out of time is a ``partial`` result,
not a failure: the next week reads another random sample, and nothing here raises an alert unless a read
actually fails.

* check: restic's structural check plus a random ~500 MB of the stored data read back and hashed (a fixed
  byte size, so the cost stays flat as the repository grows);
* spot restore: the newest PostgreSQL dump streams out and must end with its trailer, and a few small
  files of one project restore and are verified;
* prune: unused data is removed from Drive in small repacks, from the job's own qualified authority;
* the size of the retired T7 restic repository, for ``st backup old``.

``python -m app.tasks.backup_verify``
"""

from __future__ import annotations

import contextlib
import json
import secrets
import shutil
import subprocess
import sys
from collections.abc import Mapping
from typing import Any

from ..logging_config import get_logger
from ..utils.shared_paths import get_workspaces_root
from .backup_database import POSTGRES_DUMP_NAME
from .backup_offsite import (
    SHORT_TIMEOUT_SECONDS,
    Repo,
    Target,
    _last_error,
    _now,
    load_target,
    prepare_runtime,
    project_tags,
    read_state,
    trim_runtime,
    update_verify,
)

logger = get_logger(__name__)

LANE = "verify"
CHECK_SAMPLE = "500M"
CHECK_BOUND_SECONDS = 15 * 60
DUMP_BOUND_SECONDS = 20 * 60
PROJECT_BOUND_SECONDS = 10 * 60
PRUNE_BOUND_SECONDS = 30 * 60
PRUNE_REPACK_LIMIT = "2G"  # per run; a prune that stops at its bound resumes next week
PRUNE_MIN_FREE_BYTES = 10 * 1024**3  # prune caches every snapshot's trees (~2.5 GB with 2.4k snapshots); it waits a week when scratch is this tight
TIMED_OUT = 124  # run_process's exit status for a command stopped at its bound


def run_check(repo: Repo, previous: Mapping[str, Any] | None) -> dict[str, Any]:
    """Structural check plus a random byte-sized sample of the data. Out of time is ``partial``, not a failure."""
    previous = previous or {}
    started = _now()
    result = repo.restic("check", f"--read-data-subset={CHECK_SAMPLE}", timeout=CHECK_BOUND_SECONDS)
    record: dict[str, Any] = {"checked_at": started.isoformat(), "sample": CHECK_SAMPLE, "duration_s": round((_now() - started).total_seconds(), 1),
                              "last_ok_at": previous.get("last_ok_at"), "failures": int(previous.get("failures") or 0)}
    if result.returncode == 0:
        return {**record, "status": "ok", "last_ok_at": started.isoformat(), "failures": 0}
    if result.returncode == TIMED_OUT:
        return {**record, "status": "partial", "note": f"stopped at the {CHECK_BOUND_SECONDS // 60}-minute limit; another sample is read next week"}
    return {**record, "status": "failed", "error": _last_error(result), "failures": record["failures"] + 1}


def _small_files(repo: Repo, snapshot_id: str, base: str) -> list[str]:
    listing = repo.restic("ls", "--json", snapshot_id, base, timeout=SHORT_TIMEOUT_SECONDS, capture=True)  # one level: restic ls is not recursive
    files = []
    for line in listing.stdout.splitlines():
        try:
            node = json.loads(line)
        except ValueError:
            continue
        if node.get("type") == "file" and node.get("path", "").rsplit("/", 1)[0] == base and 0 < int(node.get("size") or 0) <= 262144:
            files.append(node["path"])
    return files[:12]


def _spot_project(repo: Repo, snapshot_id: str, problems: list[str]) -> dict[str, Any]:
    projects = [tag[8:] for tag in project_tags()]
    if not projects:
        return {"status": "skipped"}
    start = _now().toordinal() % len(projects)
    for step in range(len(projects)):  # the day's pick, or the next project that has small top-level files
        project = projects[(start + step) % len(projects)]
        base = f"{get_workspaces_root() / 'projects' / project}"
        files = _small_files(repo, snapshot_id, base)
        if files:
            break
    else:
        return {"status": "skipped", "reason": "no project has small top-level files"}
    target = repo.runtime.root / f"spot-{secrets.token_hex(4)}"
    try:
        target.mkdir(mode=0o700, parents=True)
        result = repo.restic("restore", snapshot_id, "--target", str(target), "--verify", *(a for path in files for a in ("--include", path)),
                             timeout=PROJECT_BOUND_SECONDS)
        if result.returncode == TIMED_OUT:
            return {"project": project, "status": "partial", "files": len(files)}
        missing = [path for path in (target / path.lstrip("/") for path in files) if not path.is_file()]
        if result.returncode or missing:
            problems.append(f"project {project} did not restore")
            return {"project": project, "status": "failed", "files": len(files), "missing": len(missing)}
        return {"project": project, "status": "ok", "files": len(files), "snapshot_id": snapshot_id}
    finally:
        shutil.rmtree(target, ignore_errors=True)


def spot_restore(repo: Repo, jobs: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Stream the newest PostgreSQL dump out of Drive and restore a few small project files, each within its bound."""
    record: dict[str, Any] = {"at": _now().isoformat()}
    problems: list[str] = []
    postgres = (jobs.get("postgres") or {}).get("snapshot_id")
    if postgres:
        dump = repo.restic("dump", postgres, "/" + POSTGRES_DUMP_NAME, timeout=DUMP_BOUND_SECONDS)
        # Only the last lines of the stream are kept: the trailer proves a complete, loadable cluster dump.
        trailer = "PostgreSQL database cluster dump complete" in dump.stdout
        record["postgres"] = {"snapshot_id": postgres, "trailer": trailer}
        if dump.returncode == TIMED_OUT:
            record["postgres"]["partial"] = True
        elif dump.returncode or not trailer:
            problems.append("postgres dump did not restore completely")
    workspaces = (jobs.get("workspaces") or {}).get("snapshot_id")
    if workspaces:
        record["project"] = _spot_project(repo, workspaces, problems)
    partial = bool((record.get("postgres") or {}).get("partial")) or (record.get("project") or {}).get("status") == "partial"
    record["status"] = "failed" if problems else "partial" if partial else "ok"
    # A restore that fails once may be Drive having a bad hour; only repeats are a problem (backup_overview).
    record["failures"] = int((previous or {}).get("failures") or 0) + 1 if problems else 0
    if problems:
        record["error"] = "; ".join(problems)[:300]
    return record


def prune(repo: Repo, now_iso: str) -> dict[str, Any]:
    """Free the space forgotten snapshots held, in small repacks. Out of time is fine: the next week continues."""
    if shutil.disk_usage(repo.runtime.cache).free < PRUNE_MIN_FREE_BYTES:
        return {"prune_partial_at": now_iso, "prune_error": None}
    result = repo.restic("prune", "--max-unused", "10%", "--max-repack-size", PRUNE_REPACK_LIMIT, timeout=PRUNE_BOUND_SECONDS, permanent_delete=True)
    if result.returncode == 0:
        return {"pruned_at": now_iso, "prune_error": None}
    if result.returncode == TIMED_OUT:
        return {"prune_partial_at": now_iso, "prune_error": None}
    return {"prune_error": _last_error(result)}


def old_repository_bytes(target: Target) -> dict[str, Any]:
    """The retired restic repository on the T7: nothing writes to it any more."""
    if target.local_repository is None:
        return {}
    measured: dict[str, Any] = {"local_repository_path": str(target.local_repository)}
    with contextlib.suppress(IndexError, ValueError, subprocess.TimeoutExpired):
        out = subprocess.run(["du", "-sb", "--", str(target.local_repository)], capture_output=True, text=True, check=False, timeout=600)
        measured["local_repository_bytes"] = int(out.stdout.split()[0])
    return measured


def run() -> dict[str, Any]:
    started = _now()
    state = read_state()
    if state.get("last_status") == "running":
        return {"skipped": "the backup is running; the next weekly run reads back"}
    target = load_target()
    runtime = prepare_runtime(target, LANE)
    repo = Repo(target, runtime)
    steps: dict[str, Any] = {}

    def step(name: str, action: Any) -> Any:
        begun = _now()
        try:
            value = action()
        except Exception as exc:  # a step failing never hides the others
            logger.exception("offsite_verify_step_failed", step=name)
            value = {"status": "failed", "error": str(exc)[:300]} if name != "prune" else {"prune_error": str(exc)[:300]}
        steps[name] = {"seconds": round((_now() - begun).total_seconds(), 1), "status": (value or {}).get("status", "ok")}
        trim_runtime(runtime)  # the cache never carries past a step beyond its cap
        return value

    try:
        update_verify(check=step("check", lambda: run_check(repo, state.get("check"))))
        update_verify(spot_restore=step("spot_restore", lambda: spot_restore(repo, state.get("jobs") or {}, state.get("spot_restore"))))
        update_verify(maintenance=step("prune", lambda: prune(repo, _now().isoformat())))
        update_verify(legacy=step("old_repository", lambda: old_repository_bytes(target)))
    finally:
        cache_bytes = trim_runtime(runtime)
        run_record = {"started_at": started.isoformat(), "finished_at": _now().isoformat(), "steps": steps, "cache_bytes": cache_bytes}
        update_verify(verify_run=run_record)
    return run_record


def main() -> int:
    print(json.dumps(run(), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
