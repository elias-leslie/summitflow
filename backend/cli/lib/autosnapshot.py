"""Autosnapshot policy library — baseline, periodic sweep, and retention pruning.

Provides the automation backbone for Btrfs-backed snapshots:
- ``ensure_baseline``: idempotent baseline snapshot for scope activation (claim, session start)
- ``sweep_periodic``: periodic safety-net snapshots for active scopes
- ``prune_scope`` / ``prune_all``: retention enforcement per scope
- ``enumerate_active_scopes``: walk Btrfs-backed lanes and projects
"""

from __future__ import annotations

import contextlib
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
    auto_keep_per_scope: int = 10
    manual_keep_per_scope: int = 20


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

    auto_excess = auto_entries[: max(0, len(auto_entries) - policy.auto_keep_per_scope)]
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
    """Enforce retention policy across all active scopes."""
    results: dict[str, list[QuickSnapshot]] = {}
    for project_id, scope in enumerate_active_scopes():
        key = f"{project_id}/{scope.scope_type}:{scope.scope_name}"
        pruned = prune_scope(
            project_id=project_id, scope=scope, policy=policy, dry_run=dry_run,
        )
        if pruned:
            results[key] = pruned
    return results
