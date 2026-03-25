"""Autosnapshot policy library — baseline, lifecycle, periodic, and retention pruning.

Provides the automation backbone for Btrfs-backed snapshots:
- ``ensure_baseline``: idempotent baseline snapshot for scope activation (claim, session start)
- ``capture_lifecycle_baseline``: best-effort protective snapshot before destructive lifecycle cleanup
- ``sweep_periodic``: periodic safety-net snapshots for active scopes
- ``prune_scope`` / ``prune_all``: retention enforcement per scope
- ``enumerate_prunable_scopes``: walk Btrfs-backed lanes/projects plus retained orphan manifests
"""

from __future__ import annotations

import contextlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .quick_snapshots import (
    QuickSnapshot,
    SnapshotScope,
    capture_snapshot,
    delete_subvolume,
    load_manifest,
    save_manifest,
)
from .worktree_paths import (
    get_workspaces_root,
    workspaces_root_available,
)


@dataclass(frozen=True)
class AutosnapshotPolicy:
    """Retention and interval policy for automatic snapshots."""

    lane_interval_minutes: int = 60
    project_interval_minutes: int = 1440
    baseline_stale_minutes: int = 30
    auto_keep_per_scope: int | None = None
    lane_auto_keep_per_scope: int = 24
    project_auto_keep_per_scope: int = 7
    archived_lane_auto_keep_per_scope: int = 3
    archived_lane_keep_per_project: int = 3
    manual_keep_per_scope: int = 20

    def to_dict(self) -> dict[str, int]:
        data = {
            "lane_interval_minutes": self.lane_interval_minutes,
            "project_interval_minutes": self.project_interval_minutes,
            "baseline_stale_minutes": self.baseline_stale_minutes,
            "lane_auto_keep_per_scope": self.lane_auto_keep_per_scope,
            "project_auto_keep_per_scope": self.project_auto_keep_per_scope,
            "archived_lane_auto_keep_per_scope": self.archived_lane_auto_keep_per_scope,
            "archived_lane_keep_per_project": self.archived_lane_keep_per_project,
            "manual_keep_per_scope": self.manual_keep_per_scope,
        }
        if self.auto_keep_per_scope is not None:
            data["auto_keep_per_scope"] = self.auto_keep_per_scope
        return data

    def auto_keep_for_scope(
        self,
        scope: SnapshotScope,
        *,
        scope_state: str = "active",
    ) -> int:
        if self.auto_keep_per_scope is not None:
            return self.auto_keep_per_scope
        if scope_state == "archived" and scope.scope_type == "lane":
            return self.archived_lane_auto_keep_per_scope
        if scope.scope_type == "project":
            return self.project_auto_keep_per_scope
        return self.lane_auto_keep_per_scope


DEFAULT_POLICY = AutosnapshotPolicy()


def _scope_key(project_id: str, scope: SnapshotScope) -> str:
    return f"{project_id}/{scope.scope_type}:{scope.scope_name}"


def _minutes_since(iso_timestamp: str) -> float:
    """Return elapsed minutes since *iso_timestamp*."""
    created = datetime.fromisoformat(iso_timestamp)
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return (datetime.now(UTC) - created).total_seconds() / 60.0


def _newest_snapshot_age_minutes(entries: list[QuickSnapshot]) -> float | None:
    """Age of the most recent snapshot in *entries*, or None if empty."""
    if not entries:
        return None
    newest = max(entries, key=lambda e: e.created_at)
    return _minutes_since(newest.created_at)


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

    age = _newest_snapshot_age_minutes(entries)
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
    """Walk Btrfs workspaces and return ``(project_id, scope)`` pairs.

    Filters to directories containing a ``.git`` file or directory (real scopes).
    """
    if not workspaces_root_available():
        return []

    scopes: list[tuple[str, SnapshotScope]] = []
    root = get_workspaces_root()

    # Lanes: /srv/workspaces/lanes/<project>/<lane>/
    lanes_root = root / "lanes"
    if lanes_root.is_dir():
        for project_dir in sorted(lanes_root.iterdir()):
            if not project_dir.is_dir():
                continue
            project_id = project_dir.name
            for lane_dir in sorted(project_dir.iterdir()):
                if lane_dir.is_dir() and (lane_dir / ".git").exists():
                    scopes.append((
                        project_id,
                        SnapshotScope("lane", lane_dir.name, lane_dir.resolve()),
                    ))

    # Projects: /srv/workspaces/projects/<project>/
    projects_root = root / "projects"
    if projects_root.is_dir():
        for project_dir in sorted(projects_root.iterdir()):
            if project_dir.is_dir() and (project_dir / ".git").exists():
                scopes.append((
                    project_dir.name,
                    SnapshotScope("project", project_dir.name, project_dir.resolve()),
                ))

    return scopes


def _scope_from_manifest_entries(entries: list[QuickSnapshot]) -> tuple[str, SnapshotScope] | None:
    if not entries:
        return None
    latest = max(entries, key=lambda entry: entry.created_at)
    return (
        latest.project_id,
        SnapshotScope(
            latest.scope_type,
            latest.scope_name,
            Path(latest.worktree_path),
        ),
    )


def _scope_state_needs_snapshot(repo_root: Path, entries: list[QuickSnapshot]) -> bool:
    """Return True when a new automatic snapshot would capture new clean-state protection."""
    from .quick_snapshots import _git, _head_oid

    current_head = _head_oid(repo_root)
    if current_head is None:
        return True

    status = _git(
        repo_root,
        ["status", "--short", "--untracked-files=all"],
        check=True,
    )
    if status.stdout.strip():
        return True

    latest = max(entries, key=lambda entry: entry.created_at)
    return latest.head_oid != current_head


def enumerate_snapshot_scopes(
    *,
    include_archived: bool = False,
) -> list[tuple[str, SnapshotScope, str]]:
    """Return snapshot scopes as ``(project_id, scope, state)`` tuples.

    Active scopes map to real current Btrfs-backed worktrees/projects. Archived
    scopes are retained recovery manifests for deleted or retired lanes.
    """
    scopes_by_key: dict[str, tuple[str, SnapshotScope, str]] = {}
    for project_id, scope in enumerate_active_scopes():
        scopes_by_key[_scope_key(project_id, scope)] = (project_id, scope, "active")

    if not include_archived:
        return list(scopes_by_key.values())

    manifests_root = Path.home() / ".local" / "share" / "st" / "snaps"
    if not manifests_root.is_dir():
        return list(scopes_by_key.values())

    for project_dir in sorted(manifests_root.iterdir()):
        if not project_dir.is_dir():
            continue
        for scope_dir in sorted(project_dir.iterdir()):
            manifest_path = scope_dir / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                raw = manifest_path.read_text(encoding="utf-8")
                entries = [
                    QuickSnapshot.from_dict(item)
                    for item in json.loads(raw)
                    if isinstance(item, dict)
                ]
            except Exception:
                continue
            resolved = _scope_from_manifest_entries(entries)
            if resolved is None:
                continue
            project_id, scope = resolved
            key = _scope_key(project_id, scope)
            if key in scopes_by_key:
                continue
            scopes_by_key[key] = (project_id, scope, "archived")

    return list(scopes_by_key.values())


def enumerate_prunable_scopes() -> list[tuple[str, SnapshotScope]]:
    """Return scopes that may still have retained snapshots to prune."""
    return [
        (project_id, scope)
        for project_id, scope, _ in enumerate_snapshot_scopes(include_archived=True)
    ]


def _find_manifest_scope_dir(project_id: str, scope: SnapshotScope) -> Path | None:
    manifests_root = Path.home() / ".local" / "share" / "st" / "snaps" / project_id
    if not manifests_root.is_dir():
        return None

    wanted_key = _scope_key(project_id, scope)
    for scope_dir in sorted(manifests_root.iterdir()):
        manifest_path = scope_dir / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            raw = manifest_path.read_text(encoding="utf-8")
            entries = [
                QuickSnapshot.from_dict(item)
                for item in json.loads(raw)
                if isinstance(item, dict)
            ]
        except Exception:
            continue
        resolved = _scope_from_manifest_entries(entries)
        if resolved is None:
            continue
        manifest_project_id, manifest_scope = resolved
        if _scope_key(manifest_project_id, manifest_scope) == wanted_key:
            return scope_dir
    return None


def _delete_entries(
    *,
    project_id: str,
    scope: SnapshotScope,
    entries: list[QuickSnapshot],
    manifest_dir: Path | None,
) -> None:
    artifact_root = manifest_dir / "artifacts" if manifest_dir is not None else None
    snapshot_roots: set[Path] = set()

    for entry in entries:
        snapshot_path = Path(entry.snapshot_path)
        if snapshot_path.exists():
            with contextlib.suppress(Exception):
                delete_subvolume(snapshot_path)
        snapshot_roots.add(snapshot_path.parent)

        if artifact_root is not None:
            artifact_dir = artifact_root / entry.id
            if artifact_dir.exists():
                shutil.rmtree(artifact_dir, ignore_errors=True)

    for snapshot_root in snapshot_roots:
        if snapshot_root.exists():
            with contextlib.suppress(OSError):
                snapshot_root.rmdir()


def _prune_entire_scope(
    *,
    project_id: str,
    scope: SnapshotScope,
    dry_run: bool = False,
) -> list[QuickSnapshot]:
    entries = load_manifest(project_id, scope)
    if not entries:
        return []

    if dry_run:
        return entries

    manifest_dir = _find_manifest_scope_dir(project_id, scope)
    _delete_entries(
        project_id=project_id,
        scope=scope,
        entries=entries,
        manifest_dir=manifest_dir,
    )
    if manifest_dir and manifest_dir.exists():
        shutil.rmtree(manifest_dir, ignore_errors=True)
    return entries


def _archived_auto_lane_scopes_to_prune(
    scopes: list[tuple[str, SnapshotScope, str]],
    *,
    policy: AutosnapshotPolicy,
) -> set[str]:
    keep_per_project = max(0, policy.archived_lane_keep_per_project)
    archived_by_project: dict[str, list[tuple[str, SnapshotScope, list[QuickSnapshot]]]] = {}

    for project_id, scope, scope_state in scopes:
        if scope_state != "archived" or scope.scope_type != "lane":
            continue
        entries = load_manifest(project_id, scope)
        if not entries:
            continue
        if any(not entry.source.startswith("auto-") for entry in entries):
            continue
        newest_at = max(entry.created_at for entry in entries)
        archived_by_project.setdefault(project_id, []).append((newest_at, scope, entries))

    prune_keys: set[str] = set()
    for project_id, items in archived_by_project.items():
        items.sort(key=lambda item: (item[0], item[1].scope_name), reverse=True)
        for _, scope, _ in items[keep_per_project:]:
            prune_keys.add(_scope_key(project_id, scope))

    return prune_keys


def sweep_periodic(
    *,
    policy: AutosnapshotPolicy = DEFAULT_POLICY,
) -> list[QuickSnapshot]:
    """Create periodic snapshots for active scopes where the interval has elapsed."""
    created: list[QuickSnapshot] = []

    for project_id, scope in enumerate_active_scopes():
        interval = (
            policy.lane_interval_minutes
            if scope.scope_type == "lane"
            else policy.project_interval_minutes
        )

        entries = load_manifest(project_id, scope)
        age = _newest_snapshot_age_minutes(entries)
        if age is not None and age < interval:
            continue
        if entries and not _scope_state_needs_snapshot(scope.path, entries):
            continue

        try:
            snap = capture_snapshot(
                "auto-periodic",
                project_id=project_id,
                cwd=scope.path,
                source="auto-periodic",
            )
            created.append(snap)
        except Exception:
            # Periodic snapshots are best-effort
            continue

    return created


def prune_scope(
    *,
    project_id: str,
    scope: SnapshotScope,
    policy: AutosnapshotPolicy = DEFAULT_POLICY,
    scope_state: str = "active",
    dry_run: bool = False,
) -> list[QuickSnapshot]:
    """Enforce retention policy for a single scope. Returns pruned entries."""
    entries = load_manifest(project_id, scope)
    if not entries:
        return []

    auto_entries = [e for e in entries if e.source.startswith("auto-")]
    manual_entries = [e for e in entries if not e.source.startswith("auto-")]

    # Sort oldest-first for pruning
    auto_entries.sort(key=lambda e: e.created_at)
    manual_entries.sort(key=lambda e: e.created_at)

    auto_limit = policy.auto_keep_for_scope(scope, scope_state=scope_state)
    auto_excess = auto_entries[: max(0, len(auto_entries) - auto_limit)]
    manual_excess = manual_entries[: max(0, len(manual_entries) - policy.manual_keep_per_scope)]
    to_prune = auto_excess + manual_excess

    if not to_prune:
        return []

    if dry_run:
        return to_prune

    manifest_dir = _find_manifest_scope_dir(project_id, scope)
    prune_ids = {e.id for e in to_prune}
    _delete_entries(
        project_id=project_id,
        scope=scope,
        entries=to_prune,
        manifest_dir=manifest_dir,
    )

    remaining = [e for e in entries if e.id not in prune_ids]
    if remaining:
        save_manifest(project_id, scope, remaining)
    elif manifest_dir and manifest_dir.exists():
        shutil.rmtree(manifest_dir, ignore_errors=True)
    return to_prune


def prune_all(
    *,
    policy: AutosnapshotPolicy = DEFAULT_POLICY,
    dry_run: bool = False,
) -> dict[str, list[QuickSnapshot]]:
    """Enforce retention policy across active and retained orphan scopes."""
    results: dict[str, list[QuickSnapshot]] = {}
    scopes = list(enumerate_snapshot_scopes(include_archived=True))
    drop_scope_keys = _archived_auto_lane_scopes_to_prune(scopes, policy=policy)

    for project_id, scope, scope_state in scopes:
        key = f"{project_id}/{scope.scope_type}:{scope.scope_name}"
        if _scope_key(project_id, scope) in drop_scope_keys:
            pruned = _prune_entire_scope(
                project_id=project_id,
                scope=scope,
                dry_run=dry_run,
            )
        else:
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
