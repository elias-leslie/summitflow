"""Autosnapshot policy library — baseline, lifecycle, periodic, and retention pruning.

Provides the automation backbone for Btrfs-backed project snapshots:
- ``ensure_baseline``: idempotent baseline snapshot for project activity
- ``capture_lifecycle_baseline``: best-effort protective snapshot before destructive lifecycle cleanup
- ``sweep_periodic``: periodic safety-net snapshots for active projects
- ``prune_scope`` / ``prune_all``: retention enforcement per scope
- ``enumerate_prunable_scopes``: walk Btrfs-backed projects plus retained archived manifests
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

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
from .snapshots._physical import all_entries, physical_lock, referenced_elsewhere
from .snapshots._pruning import delete_managed_readonly
from .workspace_paths import (
    get_workspaces_root,
    workspaces_root_available,
)

_AUTO_SOURCE_PREFIX = "auto-"


def delete_subvolume(path: Path) -> None:
    """Pruning-only deletion; generic rollback/source deletion stays unprivileged."""
    recovery_store = get_workspaces_root().absolute() / ".snapshots" / "recoveries"
    project = path.parent.name if path.parent.parent == recovery_store else None
    delete_managed_readonly(path, recovery_project=project)


def _delete_released_copy(entry: QuickSnapshot, path: Path) -> None:
    _require_prunable_root(entry, path)
    # Legacy copies outside .snapshots retain their existing unprivileged cleanup.
    if path.parent == get_workspaces_root().absolute() / ".snapshots" / "recoveries" / entry.project_id:
        delete_subvolume(path)
    else:
        from .quick_snapshots import delete_subvolume as delete_legacy

        delete_legacy(path)


def _require_prunable_root(entry: QuickSnapshot, path: Path) -> None:
    target = path.absolute()
    for root in (entry.scope_path, entry.repo_root, entry.capture_root):
        if root and (target == Path(root).absolute() or target in Path(root).absolute().parents):
            raise RuntimeError(f"Pruning refuses a live source or capture root: {path}")


@dataclass(frozen=True)
class AutosnapshotPolicy:
    """Retention and interval policy for automatic project snapshots."""

    interval_minutes: int = 15
    baseline_stale_minutes: int = 15
    auto_keep_per_scope: int = 768
    archived_auto_keep_per_scope: int = 3
    archived_keep_per_project: int = 3
    manual_keep_per_scope: int = 20
    recent_hours: int = 24
    hourly_days: int = 7

    def to_dict(self) -> dict[str, int]:
        return {
            "interval_minutes": self.interval_minutes,
            "baseline_stale_minutes": self.baseline_stale_minutes,
            "auto_keep_per_scope": self.auto_keep_per_scope,
            "archived_auto_keep_per_scope": self.archived_auto_keep_per_scope,
            "archived_keep_per_project": self.archived_keep_per_project,
            "manual_keep_per_scope": self.manual_keep_per_scope,
            "recent_hours": self.recent_hours,
            "hourly_days": self.hourly_days,
        }

    def auto_keep_for_scope(
        self,
        *,
        scope_state: str = "active",
    ) -> int:
        if scope_state == "archived":
            return self.archived_auto_keep_per_scope
        return self.auto_keep_per_scope


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
            if project_dir.is_dir() and (project_dir / ".git").exists() and str(project_dir.resolve()) not in recovery_roots:
                scopes.append((
                    project_dir.name,
                    SnapshotScope("project", project_dir.name, project_dir.resolve()),
                ))

    return scopes


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


def _delete_entries(*, project_id: str, scope: SnapshotScope, entries: list[QuickSnapshot], manifest_dir: Path | None) -> list[QuickSnapshot]:
    """Return only physically deleted points. Failed deletion remains retryable."""
    deleted = []
    for entry in entries:
        try:
            if any(not copy.get("deleted_at") for copy in recovery_catalogue(entry)):
                raise RuntimeError("Recovery copies must be released and physically cleaned before pruning this point")
            _require_prunable_root(entry, Path(entry.snapshot_path))
            shared = referenced_elsewhere(entry)
            if not shared:
                delete_subvolume(Path(entry.snapshot_path))
            if not shared and Path(entry.snapshot_path).exists():
                raise OSError("Physical snapshot remains after deletion")
        except Exception as exc:
            entry.deletion_error = str(exc)
            logging.getLogger(__name__).warning("snapshot deletion deferred %s: %s", entry.id, exc)
            continue
        deleted.append(entry)
        if manifest_dir:
            artifact = manifest_dir / "artifacts" / entry.id
            if artifact.exists():
                shutil.rmtree(artifact, ignore_errors=True)
    return deleted


LAST_SWEEP_REPORT: list[dict[str, str]] = []
LAST_PRUNE_REPORT: list[dict[str, str]] = []


def sweep_periodic(*, policy: AutosnapshotPolicy = DEFAULT_POLICY) -> list[QuickSnapshot]:
    """Capture saved changes; retention runs even during unchanged or pressured periods."""
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
            prune_scope(project_id=project_id, scope=scope, policy=policy)
            for report in LAST_PRUNE_REPORT[report_start:]:
                LAST_SWEEP_REPORT.append({"project_id": project_id, "status": "recovery copy " + report["action"],
                    "reason": report["error"] or report["root_path"]})
        except Exception as exc:
            LAST_SWEEP_REPORT.append({"project_id": project_id, "status": "cleanup deferred", "reason": str(exc)})
    return created


def _protected_ids(entries: list[QuickSnapshot], now: datetime) -> set[str]:
    protected = set()
    unfinished = [e for e in entries if e.unfinished]
    if unfinished:
        protected.add(_latest_entry(unfinished).id)
    for entry in entries:
        if entry.unfinished is None:
            protected.add(entry.id)
        if entry.recovery_active or any(not copy.get("deleted_at") for copy in recovery_catalogue(entry)):
            protected.add(entry.id)
        if entry.pin_reason:
            expiry = datetime.fromisoformat(entry.pin_until) if entry.pin_until else None
            if expiry is not None and expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)
            if expiry is None or expiry > now:
                protected.add(entry.id)
    return protected


def _retention_candidates(entries: list[QuickSnapshot], policy: AutosnapshotPolicy) -> list[QuickSnapshot]:
    now = datetime.now(UTC)
    protected = _protected_ids(entries, now)
    autos = sorted([e for e in entries if e.source.startswith(_AUTO_SOURCE_PREFIX)], key=lambda e: e.created_at, reverse=True)
    # Keep the newest point even when a clean project has been idle for over a week.
    if autos:
        protected.add(autos[0].id)
    buckets = set()
    prune = []
    for entry in autos:
        created = datetime.fromisoformat(entry.created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        age = now - created
        bucket = created.astimezone(UTC).strftime("%Y-%m-%dT%H")
        keep = age <= timedelta(hours=policy.recent_hours)
        if not keep and age <= timedelta(days=policy.hourly_days) and bucket not in buckets:
            keep = True
        buckets.add(bucket)
        if not keep and entry.id not in protected:
            prune.append(entry)
    manuals = sorted([e for e in entries if not e.source.startswith(_AUTO_SOURCE_PREFIX)], key=lambda e: e.created_at, reverse=True)
    prune.extend(e for e in manuals[policy.manual_keep_per_scope:] if e.id not in protected)
    return prune


def prune_scope(
    *,
    project_id: str,
    scope: SnapshotScope,
    policy: AutosnapshotPolicy = DEFAULT_POLICY,
    scope_state: str = "active",
    dry_run: bool = False,
) -> list[QuickSnapshot]:
    """Enforce retention policy for a single scope. Returns pruned entries."""
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
        to_prune = _retention_candidates(entries, policy)
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


def prune_all(
    *,
    policy: AutosnapshotPolicy = DEFAULT_POLICY,
    dry_run: bool = False,
) -> dict[str, list[QuickSnapshot]]:
    """Enforce retention policy across active and retained orphan scopes."""
    results: dict[str, list[QuickSnapshot]] = {}
    LAST_PRUNE_REPORT.clear()
    scopes = list(enumerate_snapshot_scopes(include_archived=True))
    for project_id, scope, scope_state in scopes:
        key = _scope_key(project_id, scope)
        pruned = prune_scope(
            project_id=project_id,
            scope=scope,
            policy=policy,
            scope_state=scope_state,
            dry_run=dry_run,
        )
        if pruned:
            results[key] = pruned
    return results
