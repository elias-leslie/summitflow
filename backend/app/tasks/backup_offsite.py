"""The one daily off-site backup: restic reads the btrbk snapshots straight into the Drive repository.

btrbk (``backup_btrbk``) takes a consistent, read-only snapshot of every host
subvolume each run and keeps only the newest as its incremental parent. Once a
day this job mounts those snapshots at their real paths in a private mount
namespace and runs ``restic backup`` over them, so:

* nothing is copied or staged: the only local writes are restic's capped
  metadata cache and pack spool on tmpfs, removed when they pass a cap;
* every subvolume is read at the instant btrbk froze it;
* snapshot paths are the real paths (``/srv/workspaces/projects/aico``), so
  restic matches the previous snapshot and re-reads only what changed, and
  ``restic restore --include <path>`` restores a project by its real path.

PostgreSQL and Redis stream their dumps into restic; registered Proxmox and
off-disk sources (see ``backup_sources``) stream or back up directly. The job
holds the host-recovery lock, so btrbk cannot replace a snapshot it is reading.

Reading the copy back (``backup_verify``) is a separate, weekly, time-bounded job: Drive's speed
can never delay a backup.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..logging_config import get_logger
from ..storage import backups as backup_store
from ..utils.shared_paths import get_workspaces_root
from .backup_database import (
    POSTGRES_DUMP_NAME,
    REDIS_DUMP_NAME,
    postgres_dump_invocation,
    redis_dump_invocation,
)
from .backup_proc import Result, run_process

logger = get_logger(__name__)

TAG = "offsite"
EXCLUDES = Path(__file__).with_name("backup_offsite.excludes")
JOB_TIMEOUT_SECONDS = 10 * 3600
SHORT_TIMEOUT_SECONDS = 900
CACHE_CAP_BYTES = 1024**3  # restic's metadata caches for the Drive repository measure ~0.2 GB; past this they are dropped and rebuilt
LOCK_WAIT = "5m"  # a backup meeting the weekly prune waits for it instead of failing
LEGACY_AFTER_GOOD_RUNS = 3
STATE_HISTORY = 30
# restic needs only these from a root-owned environment; nothing else is inherited.
_PASSTHROUGH = ("PATH", "LANG", "LC_ALL", "HOME", "USER")

# What each host subvolume contributes. ``binds`` are directories of the snapshot mounted over
# the live path before restic reads it (a whole subvolume binds at its own mount point).
# Subvolumes not listed here are local-only: docker (images; PostgreSQL is dumped logically),
# models (downloads) and var_log.
SUBVOLUME_JOBS: dict[str, dict[str, Any]] = {
    "workspaces": {"mount": "/srv/workspaces", "paths": ["/srv/workspaces"]},
    "home": {"mount": "/home", "paths": ["/home"]},
    # Configuration and our own helpers only; installed software under /opt and /usr/local/lib is reinstallable.
    "root": {"mount": "/", "paths": ["/etc", "/root", "/usr/local/bin", "/usr/local/sbin", "/usr/local/libexec", "/usr/local/share", "/opt/ominull", "/var/spool"]},
}
STREAM_JOBS: dict[str, Callable[[], tuple[list[str], dict[str, str]]]] = {
    "postgres": postgres_dump_invocation,
    "redis": redis_dump_invocation,
}
_STREAM_FILES = {"postgres": POSTGRES_DUMP_NAME, "redis": REDIS_DUMP_NAME}
# A failed essential job fails the day; the others are reported on their own.
REQUIRED_JOBS = frozenset({"workspaces", "home", "root", "postgres"})


class OffsiteError(RuntimeError):
    pass


@dataclass(frozen=True)
class Target:
    """The Drive repository, from the enabled restic storage backend row."""

    backend_id: str
    repository: str
    password_file: Path
    rclone_config: Path | None
    key_directory: Path
    hostname: str
    prune_qualified: bool
    local_repository: Path | None = None
    local_password_file: Path | None = None


def load_target() -> Target:
    for backend in backup_store.list_backends(enabled_only=True):
        config = backend.get("config") or {}
        if config.get("engine") != "restic" or not config.get("restic_remote_repository"):
            continue
        key_directory = Path(config.get("restic_key_directory") or Path.home() / ".local/state/summitflow/backup-keys")
        remote_password = config.get("restic_remote_password_file")
        if not remote_password:
            raise OffsiteError("The off-site repository has no password file reference")
        rclone = config.get("restic_rclone_config")
        import socket

        return Target(
            backend_id=str(backend["id"]), repository=str(config["restic_remote_repository"]),
            password_file=Path(remote_password), rclone_config=Path(rclone) if rclone else None,
            key_directory=key_directory, hostname=str(config.get("restic_hostname") or socket.gethostname()),
            prune_qualified=bool(config.get("restic_offsite_prune_qualified")),
            local_repository=Path(config["restic_local_repository"]) if config.get("restic_local_repository") else None,
            local_password_file=Path(config["restic_local_password_file"]) if config.get("restic_local_password_file") else None,
        )
    raise OffsiteError("No enabled restic storage backend names an off-site repository")


# ---- state -----------------------------------------------------------------------------------------------------

def state_dir() -> Path:
    return Path.home() / ".local/state/summitflow/offsite"


# What the weekly verify job writes (``verify.json``), shown as part of the one state: a field is replaced, a
# section is merged. Keeping it in its own file means neither job can overwrite the other's record.
VERIFY_FIELDS = ("check", "spot_restore", "verify_run")
VERIFY_SECTIONS = {"maintenance": ("pruned_at", "prune_partial_at", "prune_error"), "legacy": ("local_repository_path", "local_repository_bytes")}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}-{os.getpid()}.tmp"
    temporary.write_text(json.dumps(value, indent=1, default=str) + "\n")
    os.replace(temporary, path)


def read_verify() -> dict[str, Any]:
    return _read_json(state_dir() / "verify.json")


def update_verify(**parts: Any) -> None:
    """Record verify results: fields replace, sections (maintenance, legacy) merge."""
    current = read_verify()
    for key, value in parts.items():
        current[key] = {**(current.get(key) or {}), **value} if key in VERIFY_SECTIONS else value
    _write_json(state_dir() / "verify.json", current)


def read_state() -> dict[str, Any]:
    state = _read_json(state_dir() / "state.json")
    verify = read_verify()
    for key in VERIFY_FIELDS:
        if key in verify:
            state[key] = verify[key]
    for key in VERIFY_SECTIONS:
        if verify.get(key):
            state[key] = {**(state.get(key) or {}), **verify[key]}
    return state


def write_state(state: Mapping[str, Any]) -> None:
    kept = {key: value for key, value in state.items() if key not in VERIFY_FIELDS}
    for key, names in VERIFY_SECTIONS.items():
        if isinstance(kept.get(key), dict):
            kept[key] = {k: v for k, v in kept[key].items() if k not in names}
    _write_json(state_dir() / "state.json", kept)


def _now() -> datetime:
    return datetime.now(UTC)


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# ---- running restic --------------------------------------------------------------------------------------------

def _runtime_directory() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / "summitflow-offsite"


def _cache_directory() -> Path:
    """Where restic's caches live: scratch, not the 3 GiB session tmpfs the desktop shares. Safe to lose; rebuilt in minutes."""
    return Path(os.environ.get("ST_SCRATCH_ROOT") or "/srv/scratch") / "summitflow-offsite"


@dataclass(frozen=True)
class Runtime:
    """tmpfs working area (pack spool, rclone config copy, excludes) plus restic's bounded caches on scratch."""

    root: Path
    store: Path | None = None  # the caches' parent; defaults to ``root`` (tests)

    @property
    def cache(self) -> Path:
        return (self.store or self.root) / "cache"

    @property
    def root_cache(self) -> Path:
        # Root-run restic creates 0700 root-owned cache files the owner's restic cannot read, so it has its own.
        return (self.store or self.root) / "cache-root"

    @property
    def tmp(self) -> Path:
        return self.root / "tmp"

    @property
    def rclone(self) -> Path:
        return self.root / "rclone.conf"

    @property
    def excludes(self) -> Path:
        # A copy outside every backed-up tree: inside the namespace a bound snapshot hides the live file.
        return self.root / "excludes"


def prepare_runtime(target: Target, lane: str = "") -> Runtime:
    """The backup's working area, or the weekly verify job's own (``lane``) so neither job trims the other's cache."""
    root = _runtime_directory() / lane
    runtime = Runtime(root, _cache_directory() / lane)
    for directory in (runtime.cache, runtime.root_cache, runtime.tmp):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    # The last run's root-run rclone left its config root-owned (it rewrites it when it refreshes a token); replace
    # the files rather than write into them, so a leftover never stops the next run. The owner's own file stays put.
    for leftover in (runtime.excludes, runtime.rclone):
        leftover.unlink(missing_ok=True)
    shutil.copyfile(EXCLUDES, runtime.excludes)
    if target.rclone_config is not None:
        shutil.copyfile(target.rclone_config, runtime.rclone)
        runtime.rclone.chmod(0o600)
    return runtime


def trim_runtime(runtime: Runtime, *, cap: int = CACHE_CAP_BYTES) -> int:
    """Empty the spool and drop the caches when together they outgrow the cap; returns the bytes they used."""
    size = sum(_tree_bytes(path) for path in (runtime.cache, runtime.root_cache))
    rm = ["sudo", "-n", "rm", "-rf", "--one-file-system", "--"]
    subprocess.run([*rm, str(runtime.tmp)], check=False, capture_output=True, timeout=120)
    if size > cap:
        subprocess.run([*rm, str(runtime.root_cache), str(runtime.cache)], check=False, capture_output=True, timeout=120)
    for child in (runtime.cache, runtime.root_cache, runtime.tmp):
        child.mkdir(mode=0o700, parents=True, exist_ok=True)
    return size


def _tree_bytes(path: Path) -> int:
    result = subprocess.run(["sudo", "-n", "du", "-sb", "--", str(path)], capture_output=True, text=True, check=False, timeout=120)
    try:
        return int(result.stdout.split()[0])
    except (IndexError, ValueError):
        return 0


def _env(target: Target, runtime: Runtime, *, root: bool, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = {key: os.environ[key] for key in _PASSTHROUGH if key in os.environ}
    env["PATH"] = ":".join(dict.fromkeys([str(Path(shutil.which("restic") or "/usr/bin/restic").parent), "/usr/local/bin", "/usr/bin", "/bin"]))
    env.update(LC_ALL="C", TMPDIR=str(runtime.tmp), RESTIC_PROGRESS_FPS="0.0166", GOMAXPROCS="4", GOMEMLIMIT="2GiB")
    if root:
        env["HOME"] = str(runtime.root)  # root's rclone and restic never write into the owner's home
    if target.rclone_config is not None:
        env["RCLONE_CONFIG"] = str(runtime.rclone if root else target.rclone_config)
    env.update(extra or {})
    return env


def _restic_args(target: Target, runtime: Runtime, *args: str, permanent_delete: bool = False, root: bool = False) -> list[str]:
    # One persistent metadata cache on scratch, capped (``trim_runtime``): it is what keeps every Drive command fast.
    command = [shutil.which("restic") or "restic", "--repo", target.repository, "--password-file", str(target.password_file),
               "--compression", "auto", "--cache-dir", str(runtime.root_cache if root else runtime.cache), "--retry-lock", LOCK_WAIT, "--json"]
    if permanent_delete and target.repository.startswith("rclone:"):
        if not target.prune_qualified:
            raise OffsiteError("Off-site permanent prune has not been qualified")
        # Drive keeps removed objects in its trash for 30 days, so an accidental forget stays recoverable.
        command.extend(["-o", "rclone.args=serve restic --stdio --drive-use-trash=true"])
    return [*command, *args]


class Repo:
    """Runs restic against the Drive repository with the run's tmpfs cache."""

    def __init__(self, target: Target, runtime: Runtime) -> None:
        self.target = target
        self.runtime = runtime

    def restic(self, *args: str, root: bool = False, binds: Sequence[tuple[str, str]] = (), timeout: float = SHORT_TIMEOUT_SECONDS,
               permanent_delete: bool = False, extra_env: Mapping[str, str] | None = None, capture: bool = False) -> Result:
        command = _restic_args(self.target, self.runtime, *args, permanent_delete=permanent_delete, root=root)
        env = _env(self.target, self.runtime, root=root, extra=extra_env)
        if root:
            command = _as_root(command, env, binds)
            env = {"PATH": env["PATH"]}
        result = run_process(command, env=env, timeout=timeout, capture=capture)
        if result.returncode == 11 and "unlock" not in args:
            # A killed run leaves a stale lock; unlock removes only stale ones (never a live holder's).
            self.restic("unlock", timeout=SHORT_TIMEOUT_SECONDS)
            result = run_process(command, env=env, timeout=timeout, capture=capture)
        return result

    def json(self, *args: str, timeout: float = SHORT_TIMEOUT_SECONDS) -> Any:
        result = self.restic(*args, timeout=timeout, capture=True)  # a snapshot listing is one long line the tail would cut
        if result.returncode:
            raise OffsiteError(f"restic {args[0]} failed (exit {result.returncode}): {_last_error(result)}")
        try:
            return json.loads(result.stdout or "null")
        except ValueError as exc:
            raise OffsiteError(f"restic {args[0]} returned invalid JSON") from exc


def _as_root(command: list[str], env: Mapping[str, str], binds: Sequence[tuple[str, str]]) -> list[str]:
    """Run restic as root in a private mount namespace where each snapshot is mounted over its live path."""
    assignments = [f"{key}={value}" for key, value in env.items()]
    script = 'while [ "$1" != -- ]; do mount --bind "$1" "$2" || exit 97; shift 2; done; shift; exec "$@"'
    pairs = [part for source, destination in binds for part in (source, destination)]
    return ["sudo", "-n", "unshare", "--mount", "--propagation", "private", "--", "env", "-i", *assignments,
            "sh", "-c", script, "sh", *pairs, "--", *command]


def _last_error(result: Result) -> str:
    lines = [line for line in (result.stderr or result.stdout).splitlines() if line.strip()]
    return (lines[-1] if lines else f"exit {result.returncode}")[:300]


# ---- planning --------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Job:
    name: str
    kind: str  # subvolume | stream | path
    tags: tuple[str, ...]
    required: bool
    binds: tuple[tuple[str, str], ...] = ()
    paths: tuple[str, ...] = ()
    command: tuple[str, ...] = ()
    filename: str = ""
    env: tuple[tuple[str, str], ...] = ()
    error: str = ""


def project_tags() -> list[str]:
    root = get_workspaces_root() / "projects"
    try:
        return sorted(f"project:{entry.name}" for entry in root.iterdir() if entry.is_dir() and re.fullmatch(r"[A-Za-z0-9._-]+", entry.name))
    except OSError:
        return []


def subvolume_jobs(points: Sequence[Mapping[str, Any]], run_id: str) -> list[Job]:
    """One job per host subvolume that has an off-site share, from the points of one btrbk run."""
    jobs = []
    snapshots = {str(point.get("source")): str(point.get("snapshot")) for point in points}
    for name, spec in SUBVOLUME_JOBS.items():
        snapshot = snapshots.get(spec["mount"])
        if not snapshot:
            raise OffsiteError(f"The btrbk run has no snapshot of {spec['mount']}")
        binds = tuple((snapshot if path == spec["mount"] else f"{snapshot}/{os.path.relpath(path, spec['mount'])}", path) for path in spec["paths"])
        tags = [TAG, f"job:{name}", f"btrbk:{run_id}"]
        if name == "workspaces":
            tags.extend(project_tags())
        jobs.append(Job(name=name, kind="subvolume", tags=tuple(tags), required=True, binds=binds, paths=tuple(spec["paths"])))
    return jobs


def stream_jobs() -> list[Job]:
    jobs = []
    for name, build in STREAM_JOBS.items():
        command, env = build()
        jobs.append(Job(name=name, kind="stream", tags=(TAG, f"job:{name}", f"source:{name}"), required=name in REQUIRED_JOBS,
                        command=tuple(command), filename=_STREAM_FILES[name], env=tuple(sorted(env.items()))))
    return jobs


def _off_host_disk(path: str) -> bool:
    """Directories on the T7/Backups drives; everything else on the host is read from the btrbk snapshots."""
    resolved = os.path.realpath(path)
    return resolved.startswith(("/media/", "/mnt/"))


def source_jobs() -> list[Job]:
    """Registered sources the host snapshots do not cover: Proxmox streams and directories on other disks."""
    from .backup_proxmox import ProxmoxGuestOffline, is_proxmox_path, plan_capture

    jobs = []
    for source in backup_store.list_sources():
        if not source.get("enabled"):
            continue
        source_id, path = str(source["id"]), str(source.get("path") or "")
        tags = (TAG, f"job:{source_id}", f"source:{source_id}")
        if is_proxmox_path(path):
            try:
                plan = plan_capture(source_id, path)
            except Exception as exc:
                if isinstance(exc, ProxmoxGuestOffline):
                    # A powered-off guest cannot have changed; its last snapshot stays current.
                    jobs.append(Job(name=source_id, kind="offline", tags=tags, required=False))
                else:
                    jobs.append(Job(name=source_id, kind="stream", tags=tags, required=False, error=str(exc)[:300]))
                continue
            jobs.append(Job(name=source_id, kind="stream", tags=tags, required=False, command=tuple(plan["command"]),
                            filename=plan["target"].filename))
        elif path and _off_host_disk(path) and Path(path).exists():
            jobs.append(Job(name=source_id, kind="path", tags=tags, required=False, paths=(path,)))
    return jobs


# ---- one job ---------------------------------------------------------------------------------------------------

def _job_record(job: Job, result: Result, started: datetime) -> dict[str, Any]:
    summary = result.summary
    record: dict[str, Any] = {
        "name": job.name, "kind": job.kind, "required": job.required, "tags": [t for t in job.tags if not t.startswith("project:")],
        "started_at": started.isoformat(), "duration_s": round((_now() - started).total_seconds(), 1),
    }
    if result.ok and summary.get("snapshot_id"):
        record.update(
            status="ok", snapshot_id=summary["snapshot_id"], time=_now().isoformat(),
            files=int(summary.get("total_files_processed") or 0), bytes=int(summary.get("total_bytes_processed") or 0),
            added_bytes=int(summary.get("data_added") or 0), stored_bytes=int(summary.get("data_added_packed") or 0),
            new_files=int(summary.get("files_new") or 0), changed_files=int(summary.get("files_changed") or 0),
        )
        if result.returncode == 3:
            record["warning"] = "some files could not be read: " + _last_error(result)
    else:
        record.update(status="failed", error=_last_error(result))
    return record


def run_job(repo: Repo, job: Job) -> dict[str, Any]:
    started = _now()
    base = ["backup", "--host", repo.target.hostname, *(part for tag in job.tags for part in ("--tag", tag))]
    files = ["--exclude-file", str(repo.runtime.excludes), "--exclude-caches", "--exclude-if-present", ".nobackup"]
    head = {"name": job.name, "kind": job.kind, "required": job.required, "started_at": started.isoformat()}
    if job.kind == "offline":
        return {**head, "status": "offline"}
    if job.kind == "stream":
        if not job.command or not job.filename:
            return {**head, "status": "failed", "error": job.error or "the source could not be planned"}
        # Restic records no snapshot when the command fails, so a failed dump is never a recovery point.
        args = [*base, "--stdin-from-command", "--stdin-filename", job.filename, "--", *job.command]
        result = repo.restic(*args, timeout=JOB_TIMEOUT_SECONDS, extra_env=dict(job.env))
        if result.ok and int(result.summary.get("total_bytes_processed") or 0) <= 0:
            result.returncode, result.stderr = 1, "the stream produced no data"
    elif job.kind == "subvolume":
        result = repo.restic(*base, *files, *job.paths, root=True, binds=job.binds, timeout=JOB_TIMEOUT_SECONDS)
    else:
        result = repo.restic(*base, *files, *job.paths, timeout=JOB_TIMEOUT_SECONDS)
    return _job_record(job, result, started)


# ---- retention -------------------------------------------------------------------------------------------------

def _snapshots(repo: Repo, *filters: str) -> list[dict[str, Any]]:
    value = repo.json("snapshots", *filters, timeout=3600)
    return value if isinstance(value, list) else []


def retention_ids(snapshots: Sequence[Mapping[str, Any]], *, now: datetime, legacy_days: int) -> list[str]:
    """Legacy-shape snapshots (per-source tags, no ``offsite`` tag) older than the window, newest few always kept per source."""
    cutoff = now - timedelta(days=legacy_days)
    legacy = [item for item in snapshots if TAG not in (item.get("tags") or []) and any(str(t).startswith("source:") for t in item.get("tags") or [])]
    return sorted(str(item["id"]) for item in legacy if (_parse(item.get("time")) or now) < cutoff)


def measure_legacy(listing: Sequence[Mapping[str, Any]], previous: Mapping[str, Any] | None) -> dict[str, Any]:
    """The old per-source snapshots still in Drive (the T7 repository's size is measured by the weekly verify job)."""
    old = sum(1 for item in listing if TAG not in (item.get("tags") or []) and any(str(t).startswith("source:") for t in item.get("tags") or []))
    return {**(previous or {}), "drive_snapshots": old}


def retain(repo: Repo, state: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """Forget what the retention windows release. Space comes back at the weekly prune (``backup_verify``)."""
    settings = get_settings()
    maintenance = dict(state.get("maintenance") or {})
    record: dict[str, Any] = {"ran_at": now.isoformat(), "forget_error": None, "legacy_error": None}
    forget = repo.restic(
        "forget", "--tag", TAG, "--group-by", "host,paths",
        "--keep-daily", str(settings.backup_offsite_keep_daily), "--keep-weekly", str(settings.backup_offsite_keep_weekly),
        "--keep-monthly", str(settings.backup_offsite_keep_monthly), timeout=3600, permanent_delete=True)
    if forget.returncode:
        record["forget_error"] = _last_error(forget)
    # Old per-source snapshots from before the daily job age out here, with their stated window.
    listing = _snapshots(repo)
    legacy = retention_ids(listing, now=now, legacy_days=settings.backup_offsite_legacy_days)
    good_runs = sum(1 for item in state.get("runs") or [] if isinstance(item, dict) and item.get("status") == "ok")
    # The old per-source snapshots age out only once the daily job has proven itself for a few days.
    if legacy and forget.returncode == 0 and good_runs >= LEGACY_AFTER_GOOD_RUNS:
        old = repo.restic("forget", *legacy, timeout=3600, permanent_delete=True)
        record["legacy_forgotten"] = 0 if old.returncode else len(legacy)
        if old.returncode:
            record["legacy_error"] = _last_error(old)
    record["snapshots"] = len(listing)
    state["legacy"] = measure_legacy(listing, state.get("legacy"))
    return {**maintenance, **record}


# ---- the run ---------------------------------------------------------------------------------------------------

def offsite_due(state: Mapping[str, Any], now: datetime, *, force: bool = False) -> str | None:
    """Why a run should start now, or None. Once a local day, inside the backup window; a missed day catches up at any hour."""
    if force:
        return "requested"
    settings = get_settings()
    from zoneinfo import ZoneInfo

    local = now.astimezone(ZoneInfo(settings.backup_schedule_timezone))
    last = _parse(state.get("last_success_at"))
    attempt = _parse(state.get("last_attempt_at"))
    if last and last.astimezone(local.tzinfo).date() == local.date():
        return None
    if attempt and now - attempt < timedelta(hours=3) and state.get("last_status") == "failed":
        return None  # one retry per few hours, not a storm; the next scheduled run tries again
    if settings.backup_schedule_window:
        from ..utils.maintenance_window import MaintenanceWindow

        if MaintenanceWindow.parse(settings.backup_schedule_window).contains(now, ZoneInfo(settings.backup_schedule_timezone)):
            return "daily"
        if last is None or now - last > timedelta(hours=30):
            return "catch-up"
        return None
    return "daily"


def run_offsite(points: Sequence[Mapping[str, Any]], run_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Back up the host snapshots of one btrbk run and the database/Proxmox streams into the Drive repository."""
    started = now or _now()
    target = load_target()
    state = read_state()
    state.setdefault("first_attempt_at", started.isoformat())
    state.update(last_attempt_at=started.isoformat(), last_status="running", repository=target.repository)
    write_state(state)
    runtime = prepare_runtime(target)
    repo = Repo(target, runtime)
    run: dict[str, Any] = {"run_id": f"{started.strftime('%Y%m%dT%H%M%SZ')}", "btrbk_run_id": run_id, "started_at": started.isoformat(), "jobs": {}}
    try:
        jobs = [*subvolume_jobs(points, run_id), *stream_jobs(), *source_jobs()]
        for job in jobs:
            try:
                record = run_job(repo, job)
            except Exception as exc:  # one job failing never hides the others
                logger.exception("offsite_job_failed", job=job.name)
                record = {"name": job.name, "kind": job.kind, "required": job.required, "status": "failed", "error": str(exc)[:300]}
            run["jobs"][job.name] = record
            trim_runtime(runtime)  # the cache never grows past its cap across jobs
            state["current_run"] = run
            write_state(state)
        failed_required = [name for name, record in run["jobs"].items() if record.get("required") and record.get("status") != "ok"]
        failed_optional = [name for name, record in run["jobs"].items() if not record.get("required") and record.get("status") == "failed"]
        run["status"] = "failed" if failed_required else "ok"
        if failed_required:
            run["error"] = f"{', '.join(failed_required)} did not back up"
        elif failed_optional:
            run["warning"] = f"{', '.join(failed_optional)} did not back up"
        latest = dict(state.get("jobs") or {})
        latest.update({name: record for name, record in run["jobs"].items() if record.get("status") == "ok"})
        state["jobs"] = latest
        if run["status"] == "ok":
            state["maintenance"] = retain(repo, state, now=started)
    except Exception as exc:
        logger.exception("offsite_run_failed")
        run.update(status="failed", error=str(exc)[:300])
    finally:
        run["finished_at"] = _now().isoformat()
        run["cache_bytes"] = trim_runtime(runtime)
    state.pop("current_run", None)
    state["last_status"] = run["status"]
    if run["status"] == "ok":
        state.update(last_success_at=run["finished_at"], last_error=None)
    else:
        state["last_error"] = run.get("error")
    state["last_run"] = run
    history = [item for item in (state.get("runs") or []) if isinstance(item, dict)]
    history.append({key: run.get(key) for key in ("run_id", "btrbk_run_id", "started_at", "finished_at", "status", "error")})
    state["runs"] = history[-STATE_HISTORY:]
    write_state(state)
    return run


def recover_state() -> dict[str, Any]:
    """Self-heal at the start of a run, which holds the host lock: a run still marked running was interrupted."""
    state = read_state()
    if state.get("last_status") == "running":
        state.update(last_status="failed", last_error="the previous run was interrupted and will be redone")
        state.pop("current_run", None)
        write_state(state)
    return state
