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
    manual_keep_per_scope: int = 20

    def to_dict(self) -> dict[str, int]:
        data = {
            "lane_interval_minutes": self.lane_interval_minutes,
            "project_interval_minutes": self.project_interval_minutes,
            "baseline_stale_minutes": self.baseline_stale_minutes,
            "lane_auto_keep_per_scope": self.lane_auto_keep_per_scope,
            "project_auto_keep_per_scope": self.project_auto_keep_per_scope,
            "manual_keep_per_scope": self.manual_keep_per_scope,
        }
        if self.auto_keep_per_scope is not None:
            data["auto_keep_per_scope"] = self.auto_keep_per_scope
        return data

    def auto_keep_for_scope(self, scope: SnapshotScope) -> int:
        if self.auto_keep_per_scope is not None:
            return self.auto_keep_per_scope
        if scope.scope_type == "project":
            return self.project_auto_keep_per_scope
        return self.lane_auto_keep_per_scope


DEFAULT_POLICY = AutosnapshotPolicy()


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


def enumerate_prunable_scopes() -> list[tuple[str, SnapshotScope]]:
    """Return scopes that may still have retained snapshots to prune.

    Includes active scopes plus orphaned lane/project manifests whose working
    directories were already deleted.
    """
    scopes_by_key: dict[str, tuple[str, SnapshotScope]] = {}
    for project_id, scope in enumerate_active_scopes():
        scopes_by_key[f"{project_id}/{scope.scope_type}:{scope.scope_name}"] = (project_id, scope)

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
            scopes_by_key.setdefault(
                f"{project_id}/{scope.scope_type}:{scope.scope_name}",
                (project_id, scope),
            )

    return list(scopes_by_key.values())


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

    auto_limit = policy.auto_keep_for_scope(scope)
    auto_excess = auto_entries[: max(0, len(auto_entries) - auto_limit)]
    manual_excess = manual_entries[: max(0, len(manual_entries) - policy.manual_keep_per_scope)]
    to_prune = auto_excess + manual_excess

    if not to_prune:
        return []

    if dry_run:
        return to_prune

    prune_ids = {e.id for e in to_prune}
    for entry in to_prune:
        snapshot_path = Path(entry.snapshot_path)
        if snapshot_path.exists():
            with contextlib.suppress(Exception):
                delete_subvolume(snapshot_path)

        # Clean up artifact directory
        artifact_dir = (
            Path.home()
            / ".local"
            / "share"
            / "st"
            / "snaps"
            / project_id
            / f"{entry.scope_type}-{entry.scope_name}"
            / "artifacts"
            / entry.id
        )
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir, ignore_errors=True)

    remaining = [e for e in entries if e.id not in prune_ids]
    save_manifest(project_id, scope, remaining)
    return to_prune


def prune_all(
    *,
    policy: AutosnapshotPolicy = DEFAULT_POLICY,
    dry_run: bool = False,
) -> dict[str, list[QuickSnapshot]]:
    """Enforce retention policy across active and retained orphan scopes."""
    results: dict[str, list[QuickSnapshot]] = {}
    for project_id, scope in enumerate_prunable_scopes():
        key = f"{project_id}/{scope.scope_type}:{scope.scope_name}"
        pruned = prune_scope(
            project_id=project_id, scope=scope, policy=policy, dry_run=dry_run,
        )
        if pruned:
            results[key] = pruned
    return results
