"""Autosnapshot policy library — baseline, lifecycle, periodic, and retention pruning.

Provides the automation backbone for Btrfs-backed project snapshots:
- ``ensure_baseline``: idempotent baseline snapshot for project activity
- ``capture_lifecycle_baseline``: best-effort protective snapshot before destructive lifecycle cleanup
- ``sweep_periodic``: periodic safety-net snapshots for active projects
- ``plan_retention`` / ``prune_all``: retention per physical point (each point is
  one read-only snapshot of the whole workspace subvolume, shared by every
  project view that recorded it), throttled deletion and orphan reaping
- ``enumerate_prunable_scopes``: walk Btrfs-backed projects plus retained archived manifests
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any

from .autosnapshot_helpers import (
    find_manifest_scope_dir,
    iter_archived_manifest_scopes,
)
from .quick_snapshots import (
    QuickSnapshot,
    SnapshotScope,
    capture_snapshot,
    cleanup_recovery_copies,
    load_manifest,
    recovery_catalogue,
    save_manifest,
)
from .snapshots._physical import all_entries, physical_lock
from .snapshots._pruning import delete_managed_readonly, managed_store, store_path
from .workspace_paths import (
    get_workspaces_root,
    workspaces_root_available,
)

_AUTO_SOURCE_PREFIX = "auto-"
_REJECTED_CAPTURE = "Capture not accepted:"  # quick_snapshots prefix for a refused point


def delete_subvolume(path: Path) -> None:
    """Pruning-only deletion; generic rollback/source deletion stays unprivileged."""
    target = store_path(path) or path
    recovery_store = managed_store() / "recoveries"
    project = target.parent.name if target.parent.parent == recovery_store else None
    delete_managed_readonly(target, recovery_project=project)


def _delete_released_copy(entry: QuickSnapshot, path: Path) -> None:
    _require_prunable_root(entry, path)
    # Legacy copies outside .snapshots retain their existing unprivileged cleanup.
    if (store_path(path) or path).parent == managed_store() / "recoveries" / entry.project_id:
        delete_subvolume(path)
    else:
        from .quick_snapshots import delete_subvolume as delete_legacy

        delete_legacy(path)


def _require_prunable_root(entry: QuickSnapshot, path: Path) -> None:
    target = path.resolve()
    for root in (entry.scope_path, entry.repo_root, entry.capture_root):
        if root and (target == Path(root).resolve() or target in Path(root).resolve().parents):
            raise RuntimeError(f"Pruning refuses a live source or capture root: {path}")


@dataclass(frozen=True)
class AutosnapshotPolicy:
    """Capture interval and retention per physical point.

    Every point snapshots the whole workspace subvolume, so retention is
    decided per point, not per project view: all points from the last
    ``recent_hours``, the newest per hour to ``hourly_hours``, the newest per
    day to ``daily_days`` (btrbk keeps the off-machine dailies). Under disk
    pressure only the newest ``pressure_keep_points`` survive. Pins, active
    recovery copies and unclassified state always hold their point.
    """

    interval_minutes: int = 15
    baseline_stale_minutes: int = 15
    recent_hours: int = 6
    hourly_hours: int = 24
    daily_days: int = 3
    archived_keep_days: int = 14  # newest point of a project whose root is gone
    pressure_keep_points: int = 3
    manual_keep_per_scope: int = 20
    max_deletes_per_run: int = 15
    delete_batch: int = 5  # deletes between waits for the Btrfs cleaner

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


DEFAULT_POLICY = AutosnapshotPolicy()


def _scope_key(project_id: str, scope: SnapshotScope) -> str:
    return f"{project_id}/{scope.scope_type}:{scope.scope_name}"


def _minutes_since(iso_timestamp: str) -> float:
    """Return elapsed minutes since *iso_timestamp*."""
    created = datetime.fromisoformat(iso_timestamp)
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return (datetime.now(UTC) - created).total_seconds() / 60.0


def _latest_entry(entries: list[QuickSnapshot]) -> QuickSnapshot:
    """Return the most recently created snapshot from *entries*."""
    return max(entries, key=lambda e: e.created_at)


def _scope_state_needs_snapshot(repo_root: Path, entries: list[QuickSnapshot]) -> bool:
    from .quick_snapshots import _head_oid
    from .snapshots._saved_work import git_transaction_clear, source_digest
    git_transaction_clear(repo_root)
    latest = _latest_entry(entries)
    return latest.source_digest != source_digest(repo_root, use_cache=True) or latest.head_oid != _head_oid(repo_root)


def ensure_baseline(
    *,
    project_id: str,
    cwd: str | Path | None = None,
    source: str = "auto-baseline",
    policy: AutosnapshotPolicy = DEFAULT_POLICY,
) -> QuickSnapshot | None:
    """Create a baseline snapshot if the scope has none or newest is stale.

    Returns the new snapshot, or ``None`` if a recent baseline already exists.
    """
    from .quick_snapshots import _resolve_repo_root, resolve_scope

    repo_root = _resolve_repo_root(cwd)
    scope = resolve_scope(repo_root, project_id)
    entries = load_manifest(project_id, scope)
    age = _minutes_since(_latest_entry(entries).created_at) if entries else None
    if age is not None and age < policy.baseline_stale_minutes:
        return None
    if entries and not _scope_state_needs_snapshot(repo_root, entries):
        return None
    return capture_snapshot(
        "auto-baseline", project_id=project_id, cwd=cwd, source=source,
    )


def ensure_all_baselines(
    *,
    policy: AutosnapshotPolicy = DEFAULT_POLICY,
) -> list[QuickSnapshot]:
    """Create baseline snapshots for active scopes whose newest snapshot is stale."""
    created: list[QuickSnapshot] = []
    for project_id, scope in enumerate_active_scopes():
        try:
            snap = ensure_baseline(
                project_id=project_id,
                cwd=scope.path,
                source="auto-baseline",
                policy=policy,
            )
        except Exception:
            continue
        if snap is not None:
            created.append(snap)
    return created


def capture_lifecycle_baseline(
    *,
    project_id: str | None,
    cwd: str | Path | None,
) -> QuickSnapshot | None:
    """Best-effort protective snapshot before destructive lifecycle cleanup.

    This never raises; lifecycle commands should continue even if snapshotting is
    unavailable or the current scope is not Btrfs-backed.
    """
    if not project_id or not cwd:
        return None
    try:
        return capture_snapshot(
            "auto-baseline",
            project_id=project_id,
            cwd=cwd,
            source="auto-baseline",
        )
    except Exception:
        return None


def enumerate_active_scopes() -> list[tuple[str, SnapshotScope]]:
    """Walk Btrfs workspaces and return active project scopes."""
    if not workspaces_root_available():
        return []

    scopes: list[tuple[str, SnapshotScope]] = []
    root = get_workspaces_root()
    recovery_roots = {str(Path(copy["root_path"]).resolve()) for point in all_entries()
        for copy in recovery_catalogue(point) if not copy.get("deleted_at")}

    # Projects: the configured workspace root/projects/<project>/
    projects_root = root / "projects"
    if projects_root.is_dir():
        for project_dir in sorted(projects_root.iterdir()):
            # Symlinked aliases (renamed projects) would duplicate their target's snapshots.
            if project_dir.is_symlink():
                continue
            if project_dir.is_dir() and (project_dir / ".git").exists() and str(project_dir.resolve()) not in recovery_roots:
                scopes.append((
                    project_dir.name,
                    SnapshotScope("project", project_dir.name, project_dir.resolve()),
                ))

    # Retired projects stop capturing; their manifests list them as archived scopes.
    retired = retired_project_ids([project_id for project_id, _ in scopes])
    return [(project_id, scope) for project_id, scope in scopes if project_id not in retired]


def retired_project_ids(project_ids: list[str]) -> set[str]:
    """Owner-retired ids among ``project_ids``; capture continues if decisions are unreadable."""
    try:
        from app.project_identity import get_project_lifecycles

        lifecycles = get_project_lifecycles(project_ids, allow_unavailable=True)
    except Exception:
        logging.getLogger(__name__).warning("retirement decisions unavailable; capturing every project")
        return set()
    return {project_id for project_id, state in lifecycles.items() if state == "retired"}


def enumerate_snapshot_scopes(
    *,
    include_archived: bool = False,
) -> list[tuple[str, SnapshotScope, str]]:
    """Return snapshot scopes as ``(project_id, scope, state)`` tuples.

    Active scopes map to real current Btrfs-backed projects. Archived
    scopes are retained recovery manifests for deleted or retired projects.
    """
    scopes_by_key: dict[str, tuple[str, SnapshotScope, str]] = {}
    for project_id, scope in enumerate_active_scopes():
        scopes_by_key[_scope_key(project_id, scope)] = (project_id, scope, "active")

    if not include_archived:
        return list(scopes_by_key.values())

    snaps_root = Path.home() / ".local" / "share" / "st" / "snaps"
    for _, project_id, scope in iter_archived_manifest_scopes(snaps_root):
        if scope.scope_type != "project":
            continue
        key = _scope_key(project_id, scope)
        if key not in scopes_by_key:
            scopes_by_key[key] = (project_id, scope, "archived")

    return list(scopes_by_key.values())


def enumerate_prunable_scopes() -> list[tuple[str, SnapshotScope]]:
    """Return scopes that may still have retained snapshots to prune."""
    return [
        (project_id, scope)
        for project_id, scope, _ in enumerate_snapshot_scopes(include_archived=True)
    ]


def _point_key(path: str | Path) -> str:
    """One physical point, whatever spelling of the workspace root recorded it."""
    rebased = store_path(Path(path))
    return str(rebased if rebased is not None else Path(path).absolute())


def _created(entry: QuickSnapshot) -> datetime:
    created = datetime.fromisoformat(entry.created_at)
    return created if created.tzinfo else created.replace(tzinfo=UTC)


# Throttle between delete batches. ``btrfs subvolume sync`` needs root, so the
# unprivileged wait is a short pause that stretches while I/O pressure is high.
SETTLE_SECONDS = 10
SETTLE_MAX_SECONDS = 180
SETTLE_IO_PRESSURE = 10.0  # /proc/pressure/io "some" avg10 percent


def _io_pressure() -> float:
    try:
        for line in Path("/proc/pressure/io").read_text().splitlines():
            if line.startswith("some"):
                return float(line.split("avg10=")[1].split()[0])
    except (OSError, IndexError, ValueError):
        pass
    return 0.0


def _settle() -> None:
    """Let the Btrfs cleaner reclaim the last batch before deleting more."""
    time.sleep(SETTLE_SECONDS)
    deadline = time.monotonic() + SETTLE_MAX_SECONDS
    while _io_pressure() >= SETTLE_IO_PRESSURE and time.monotonic() < deadline:
        time.sleep(5)


LAST_SWEEP_REPORT: list[dict[str, str]] = []
LAST_PRUNE_REPORT: list[dict[str, str]] = []
# Physical outcome of the last prune: points deleted, deletions deferred with
# their error, prunable points left for later runs, orphan subvolumes reaped.
LAST_PRUNE_SUMMARY: dict[str, Any] = {}


def _reset_summary(*, pressure: bool = False, batch: int = DEFAULT_POLICY.delete_batch) -> None:
    LAST_PRUNE_SUMMARY.clear()
    LAST_PRUNE_SUMMARY.update(pressure=pressure, selected=0, deleted=0, deferred=[], remaining=0, orphans=0, batch=max(1, batch))


_reset_summary()


def _physical_delete(path: Path, *, orphan: bool = False) -> None:
    """Delete one point, pausing between batches; raises when it remains."""
    if LAST_PRUNE_SUMMARY["deleted"] and LAST_PRUNE_SUMMARY["deleted"] % LAST_PRUNE_SUMMARY["batch"] == 0:
        _settle()
    delete_subvolume(path)
    if path.exists():
        raise OSError("Physical snapshot remains after deletion")
    LAST_PRUNE_SUMMARY["deleted"] += 1
    if orphan:
        LAST_PRUNE_SUMMARY["orphans"] += 1


def _delete_entries(*, project_id: str, scope: SnapshotScope, entries: list[QuickSnapshot], manifest_dir: Path | None) -> list[QuickSnapshot]:
    """Return entries whose view is gone. A point another view still records stays.

    The last view of a point deletes it physically; failed deletion remains
    catalogued and retryable.
    """
    batch = {(entry.project_id, entry.scope_path, entry.id) for entry in entries}
    views: dict[str, set[tuple[str, str, str]]] = {}
    for other in all_entries():
        views.setdefault(_point_key(other.snapshot_path), set()).add((other.project_id, other.scope_path, other.id))
    deleted = []
    for entry in entries:
        try:
            if any(not copy.get("deleted_at") for copy in recovery_catalogue(entry)):
                raise RuntimeError("Recovery copies must be released and physically cleaned before pruning this point")
            _require_prunable_root(entry, Path(entry.snapshot_path))
            if not views.get(_point_key(entry.snapshot_path), set()) - batch and Path(entry.snapshot_path).exists():
                _physical_delete(Path(entry.snapshot_path))
        except Exception as exc:
            rejected = (entry.deletion_error or "").startswith(_REJECTED_CAPTURE)
            entry.deletion_error = f"{_REJECTED_CAPTURE} retry cleanup failed: {exc}" if rejected else str(exc)
            logging.getLogger(__name__).warning("snapshot deletion deferred %s: %s", entry.id, exc)
            LAST_PRUNE_SUMMARY["deferred"].append({"point_id": entry.id, "path": entry.snapshot_path, "error": str(exc)})
            continue
        deleted.append(entry)
        if manifest_dir:
            artifact = manifest_dir / "artifacts" / entry.id
            if artifact.exists():
                shutil.rmtree(artifact, ignore_errors=True)
    return deleted


def sweep_periodic(*, policy: AutosnapshotPolicy = DEFAULT_POLICY) -> list[QuickSnapshot]:
    """Capture saved changes; recovery-copy cleanup runs even during unchanged or pressured periods.

    Point retention is ``prune_all``'s job (the timer runs it right after).
    """
    created = []
    LAST_SWEEP_REPORT.clear()
    for project_id, scope in enumerate_active_scopes():
        try:
            entries = load_manifest(project_id, scope)
            age = _minutes_since(_latest_entry(entries).created_at) if entries else None
            if age is not None and age < policy.interval_minutes:
                LAST_SWEEP_REPORT.append({"project_id": project_id, "status": "skip", "reason": "interval not elapsed"})
            elif entries and not _scope_state_needs_snapshot(scope.path, entries):
                LAST_SWEEP_REPORT.append({"project_id": project_id, "status": "skip", "reason": "saved source unchanged"})
            else:
                snap = capture_snapshot("auto-periodic", project_id=project_id, cwd=scope.path, source="auto-periodic")
                created.append(snap)
                LAST_SWEEP_REPORT.append({"project_id": project_id, "status": "captured", "reason": snap.id})
        except Exception as exc:
            LAST_SWEEP_REPORT.append({"project_id": project_id, "status": "skip", "reason": str(exc)})
        try:
            report_start = len(LAST_PRUNE_REPORT)
            prune_scope(project_id=project_id, scope=scope, policy=policy, allowed=frozenset())
            for report in LAST_PRUNE_REPORT[report_start:]:
                LAST_SWEEP_REPORT.append({"project_id": project_id, "status": "recovery copy " + report["action"],
                    "reason": report["error"] or report["root_path"]})
        except Exception as exc:
            LAST_SWEEP_REPORT.append({"project_id": project_id, "status": "cleanup deferred", "reason": str(exc)})
    return created


def _held(entry: QuickSnapshot, now: datetime) -> bool:
    """Unclassified state, recovery copies and unexpired pins hold any entry."""
    if entry.unfinished is None:
        return True
    if entry.recovery_active or any(not copy.get("deleted_at") for copy in recovery_catalogue(entry)):
        return True
    if entry.pin_reason:
        expiry = datetime.fromisoformat(entry.pin_until) if entry.pin_until else None
        if expiry is not None and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        if expiry is None or expiry > now:
            return True
    return False


def _discardable(entry: QuickSnapshot) -> bool:
    """A rejected capture or a point whose physical tree is gone is not a recovery point.

    Neither may hold a retention bucket or the newest-point guarantee; both
    leave the manifest on the next prune. A missing tree only counts when its
    store directory is present, so an unmounted store never drops entries.
    """
    if (entry.deletion_error or "").startswith(_REJECTED_CAPTURE):
        return True
    path = Path(entry.snapshot_path)
    return path.parent.is_dir() and not path.exists()


def _root_gone(entry: QuickSnapshot) -> bool:
    root = Path(entry.scope_path)
    return root.parent.is_dir() and not root.exists()


def plan_retention(entries: list[QuickSnapshot], policy: AutosnapshotPolicy = DEFAULT_POLICY, *,
                   pressure: bool = False, now: datetime | None = None) -> list[str]:
    """Physical points (keys) that retention would delete, oldest first.

    ``entries`` are every manifest's entries; one point is kept when any view
    of it qualifies. Active projects whose last point ages out get a fresh
    baseline from ``prune_all`` instead of pinning an old whole-workspace point.
    """
    now = now or datetime.now(UTC)
    points: dict[str, list[QuickSnapshot]] = {}
    for entry in entries:
        if not _discardable(entry):
            points.setdefault(_point_key(entry.snapshot_path), []).append(entry)
    created = {key: min(_created(entry) for entry in views) for key, views in points.items()}
    newest_first = sorted(points, key=lambda key: created[key], reverse=True)
    kept = {key for key, views in points.items() if any(_held(entry, now) for entry in views)}
    kept.update(newest_first[:max(1, policy.pressure_keep_points) if pressure else 1])
    if not pressure:
        hours: set[str] = set()
        days: set[str] = set()
        for key in newest_first:
            age = now - created[key]
            hour, day = created[key].strftime("%Y-%m-%dT%H"), created[key].strftime("%Y-%m-%d")
            recent = age <= timedelta(hours=policy.recent_hours)
            hourly = age <= timedelta(hours=policy.hourly_hours) and hour not in hours
            daily = timedelta(hours=policy.hourly_hours) < age <= timedelta(days=policy.daily_days) and day not in days
            if recent or hourly or daily:
                kept.add(key)
            if age <= timedelta(hours=policy.hourly_hours):
                hours.add(hour)
            if age <= timedelta(days=policy.daily_days):
                days.add(day)
        scopes: dict[tuple[str, str, str], list[QuickSnapshot]] = {}
        for views in points.values():
            for entry in views:
                scopes.setdefault((entry.project_id, entry.scope_type, entry.scope_name), []).append(entry)
        for views in scopes.values():
            views.sort(key=_created, reverse=True)
            manual = [entry for entry in views if not entry.source.startswith(_AUTO_SOURCE_PREFIX)]
            kept.update(_point_key(entry.snapshot_path) for entry in manual[:policy.manual_keep_per_scope])
            unfinished = next((entry for entry in views if entry.unfinished), None)
            if unfinished and now - _created(unfinished) <= timedelta(days=policy.daily_days):
                kept.add(_point_key(unfinished.snapshot_path))
            if _root_gone(views[0]) and now - _created(views[0]) <= timedelta(days=policy.archived_keep_days):
                kept.add(_point_key(views[0].snapshot_path))
    return [key for key in reversed(newest_first) if key not in kept]


def _retention_candidates(entries: list[QuickSnapshot], allowed: set[str] | frozenset[str]) -> list[QuickSnapshot]:
    """This view's entries for points selected this run, plus discardable entries nothing holds."""
    now = datetime.now(UTC)
    prune = [entry for entry in entries if not _discardable(entry) and _point_key(entry.snapshot_path) in allowed]
    prune.extend(entry for entry in entries if _discardable(entry) and not _held(entry, now))
    return prune


def prune_scope(
    *,
    project_id: str,
    scope: SnapshotScope,
    policy: AutosnapshotPolicy = DEFAULT_POLICY,
    scope_state: str = "active",
    dry_run: bool = False,
    allowed: set[str] | frozenset[str] | None = None,
    pressure: bool = False,
) -> list[QuickSnapshot]:
    """Clean recovery copies and drop this view of the points selected for deletion.

    ``allowed`` is the run's selection from ``plan_retention``; without one
    the scope plans for itself, capped at ``policy.max_deletes_per_run``.
    """
    from .snapshots._saved_work import scope_lock
    with physical_lock(), scope_lock(project_id, scope):
        entries = load_manifest(project_id, scope)
        unknown = [entry.id for entry in entries if entry.unfinished is None]
        if unknown:
            logging.getLogger(__name__).warning(
                "snapshot retention skipped %s: saved-work state unknown; inspect/classify captured tree before pruning: %s",
                project_id, ", ".join(unknown),
            )
        for entry in entries:
            roots = cleanup_recovery_copies(entry, delete_fn=partial(_delete_released_copy, entry), dry_run=dry_run)
            for root in roots:
                copy = next(copy for copy in reversed(entry.recovery_copies) if copy["root_path"] == root)
                action = "would-delete" if dry_run else "failed" if copy.get("deletion_error") else "deleted"
                LAST_PRUNE_REPORT.append({"project_id": project_id, "point_id": entry.id, "root_path": root,
                    "action": action, "error": str(copy.get("deletion_error") or "")})
        if not dry_run:
            save_manifest(project_id, scope, entries)
        if allowed is None:
            allowed = set(plan_retention(all_entries(), policy, pressure=pressure)[:policy.max_deletes_per_run])
        to_prune = _retention_candidates(entries, allowed)
        if dry_run:
            return to_prune
        if not to_prune:
            return []
        key = _scope_key(project_id, scope)
        manifest_dir = find_manifest_scope_dir(project_id, scope, key)
        deleted = _delete_entries(project_id=project_id, scope=scope, entries=to_prune, manifest_dir=manifest_dir)
        deleted_ids = {entry.id for entry in deleted}
        # Persist errors as well as successes; never erase failed physical points.
        save_manifest(project_id, scope, [e for e in entries if e.id not in deleted_ids])
        return deleted


def _point_created(leaf: Path) -> datetime | None:
    try:
        return datetime.strptime(leaf.name[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


def _owned_subvolume(leaf: Path) -> bool:
    try:
        info = leaf.lstat()
    except OSError:
        return False
    # Every Btrfs subvolume root has inode 256; the root helper re-verifies it.
    return not leaf.is_symlink() and info.st_ino == 256 and info.st_uid == os.getuid()


def reap_orphans(policy: AutosnapshotPolicy = DEFAULT_POLICY, *, limit: int, dry_run: bool = False) -> list[str]:
    """Delete read-only point leaves under the store that no manifest records.

    Captures reserve their manifest entry before snapshotting, under the same
    physical lock, so an unrecorded leaf older than ``recent_hours`` is residue.
    """
    store = managed_store()
    if limit <= 0 or not store.is_dir():
        return []
    now = datetime.now(UTC)
    reaped: list[str] = []
    with physical_lock():
        recorded = {_point_key(entry.snapshot_path) for entry in all_entries()}
        for leaf in sorted(store.glob("*/*/*/*")):
            if len(reaped) >= limit:
                break
            if leaf.parts[len(store.parts)] == "recoveries" or leaf.parent.parent.name not in {"projects", "worktrees"}:
                continue
            created = _point_created(leaf)
            if str(leaf) in recorded or created is None or now - created <= timedelta(hours=policy.recent_hours):
                continue
            if not _owned_subvolume(leaf):
                continue
            if not dry_run:
                try:
                    _physical_delete(leaf, orphan=True)
                except Exception as exc:
                    logging.getLogger(__name__).warning("orphan snapshot deletion deferred %s: %s", leaf, exc)
                    LAST_PRUNE_SUMMARY["deferred"].append({"point_id": leaf.name, "path": str(leaf), "error": str(exc)})
                    continue
            reaped.append(str(leaf))
    return reaped


def _reanchor(scope_keys: set[str]) -> None:
    """Give an active project whose last point was pruned a current baseline."""
    for project_id, scope in enumerate_active_scopes():
        if _scope_key(project_id, scope) not in scope_keys:
            continue
        try:
            if any(not _discardable(entry) for entry in load_manifest(project_id, scope)):
                continue
            ensure_baseline(project_id=project_id, cwd=scope.path)
        except Exception as exc:
            logging.getLogger(__name__).warning("snapshot baseline after prune deferred %s: %s", project_id, exc)


def prune_all(
    *,
    policy: AutosnapshotPolicy = DEFAULT_POLICY,
    dry_run: bool = False,
    pressure: bool = False,
    max_deletes: int | None = None,
) -> dict[str, list[QuickSnapshot]]:
    """Enforce point retention across active and retained orphan scopes.

    Deletes at most ``max_deletes`` points (default ``policy.max_deletes_per_run``),
    oldest first, pausing between batches; later runs continue the backlog.
    ``LAST_PRUNE_SUMMARY`` reports deletions, deferrals and the remaining backlog.
    """
    results: dict[str, list[QuickSnapshot]] = {}
    LAST_PRUNE_REPORT.clear()
    _reset_summary(pressure=pressure, batch=policy.delete_batch)
    cap = policy.max_deletes_per_run if max_deletes is None else max(0, max_deletes)
    prunable = plan_retention(all_entries(), policy, pressure=pressure)
    allowed = set(prunable[:cap])
    LAST_PRUNE_SUMMARY.update(selected=len(allowed), remaining=len(prunable) - len(allowed))
    for project_id, scope, scope_state in enumerate_snapshot_scopes(include_archived=True):
        pruned = prune_scope(project_id=project_id, scope=scope, policy=policy, scope_state=scope_state,
                             dry_run=dry_run, allowed=allowed)
        if pruned:
            results[_scope_key(project_id, scope)] = pruned
    if dry_run:
        LAST_PRUNE_SUMMARY["orphans"] = len(reap_orphans(policy, limit=cap, dry_run=True))
        return results
    reap_orphans(policy, limit=cap - LAST_PRUNE_SUMMARY["deleted"])
    _reanchor(set(results))
    return results
