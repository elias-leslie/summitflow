"""Btrfs snapshot browsing and management API.

Exposes Btrfs-backed project snapshots to the UI.
Data lives in JSON manifests on disk — no database tables.
Reuses CLI library functions from quick_snapshots and autosnapshot.
"""

from __future__ import annotations

import contextlib
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from ..logging_config import get_logger
from ..utils import safe_subprocess

logger = get_logger(__name__)

router = APIRouter()


# ─── Models ──────────────────────────────────────────────────────


class SnapshotResponse(BaseModel):
    id: str
    name: str | None = None
    project_id: str
    scope_type: str
    scope_name: str
    branch: str | None = None
    head_oid: str | None = None
    created_at: str
    source: str = "manual"
    usage: dict[str, int] | None = None
    recovery_path: str | None = None
    recovery_active: bool = False
    pin_reason: str | None = None
    deletion_error: str | None = None
    source_digest: str | None = None
    shared_capture: bool = False
    nested_subvolumes: list[str] = []
    recovery_cleanup_pending: bool = False
    recovery_deletion_error: str | None = None


class ScopeResponse(BaseModel):
    project_id: str
    scope_type: str
    scope_name: str
    scope_state: str = "active"
    snapshot_count: int
    total_bytes: int | None = None
    newest_at: str | None = None
    oldest_at: str | None = None


class PolicyResponse(BaseModel):
    interval_minutes: int
    baseline_stale_minutes: int
    auto_keep_per_scope: int
    archived_auto_keep_per_scope: int
    archived_keep_per_project: int
    recent_hours: int = 24
    hourly_days: int = 7
    manual_keep_per_scope: int


class SnapshotSummaryResponse(BaseModel):
    total_snapshots: int
    total_usage_bytes: int | None
    by_source: dict[str, int]
    by_scope_type: dict[str, int]
    scope_count: int
    active_snapshot_count: int
    archived_snapshot_count: int
    active_scope_count: int
    archived_scope_count: int
    policy: PolicyResponse
    autosnap_timer_active: bool


class SnapshotRequest(BaseModel):
    project_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    name: str | None = None


# ─── Helpers ─────────────────────────────────────────────────────


def _snapshot_to_response(snap: Any, usage: Any | None = None) -> SnapshotResponse:
    """Convert a QuickSnapshot to API response."""
    usage_dict = None
    if usage is not None:
        usage_dict = {
            "total_bytes": usage.total_bytes,
            "exclusive_bytes": usage.exclusive_bytes,
            "shared_bytes": usage.shared_bytes,
        }
    return SnapshotResponse(
        id=snap.id,
        name=snap.name,
        project_id=snap.project_id,
        scope_type=snap.scope_type,
        scope_name=snap.scope_name,
        branch=snap.branch,
        head_oid=snap.head_oid,
        created_at=snap.created_at,
        source=snap.source,
        usage=usage_dict,
        recovery_path=snap.recovery_path,
        recovery_active=snap.recovery_active,
        pin_reason=snap.pin_reason,
        deletion_error=snap.deletion_error,
        source_digest=snap.source_digest,
        shared_capture=snap.shared_capture,
        nested_subvolumes=snap.nested_subvolumes,
        recovery_cleanup_pending=any(not copy.get("active") and not copy.get("deleted_at") for copy in snap.recovery_copies),
        recovery_deletion_error=next((copy.get("deletion_error") for copy in snap.recovery_copies if copy.get("deletion_error")), None),
    )


def _is_timer_active() -> bool:
    """Check if the btrfs-autosnapshot systemd timer is active."""
    try:
        result = safe_subprocess.run(
            ["systemctl", "--user", "is-active", "btrfs-autosnapshot.timer"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False


def _get_cli_libs() -> tuple[Any, ...]:
    """Lazy-import CLI libraries to avoid import-time side effects."""
    from cli.lib.autosnapshot import DEFAULT_POLICY, enumerate_snapshot_scopes, prune_all
    from cli.lib.quick_snapshots import (
        capture_snapshot,
        list_snapshots,
        load_manifest,
        recover_snapshot,
    )

    return (capture_snapshot, list_snapshots, recover_snapshot, load_manifest,
            DEFAULT_POLICY, enumerate_snapshot_scopes, prune_all)


# ─── Endpoints ───────────────────────────────────────────────────


@router.get("/snapshots/summary", response_model=SnapshotSummaryResponse)
async def snapshot_summary(project_id: str | None = None) -> SnapshotSummaryResponse:
    """Aggregate snapshot summary with policy and timer status."""
    _, _, _, load_manifest, DEFAULT_POLICY, enumerate_snapshot_scopes, _ = _get_cli_libs()

    scopes = list(enumerate_snapshot_scopes(include_archived=True))
    if project_id:
        scopes = [s for s in scopes if s[0] == project_id]

    total_snapshots = 0
    active_snapshot_count = 0
    archived_snapshot_count = 0
    by_source: dict[str, int] = {}
    by_scope_type: dict[str, int] = {}

    for pid, scope, scope_state in scopes:
        for snap in load_manifest(pid, scope):
            total_snapshots += 1
            if scope_state == "active":
                active_snapshot_count += 1
            else:
                archived_snapshot_count += 1
            src = snap.source or "manual"
            by_source[src] = by_source.get(src, 0) + 1
            by_scope_type[snap.scope_type] = by_scope_type.get(snap.scope_type, 0) + 1

    return SnapshotSummaryResponse(
        total_snapshots=total_snapshots,
        total_usage_bytes=None,
        by_source=by_source,
        by_scope_type=by_scope_type,
        scope_count=len(scopes),
        active_snapshot_count=active_snapshot_count,
        archived_snapshot_count=archived_snapshot_count,
        active_scope_count=sum(1 for _, _, state in scopes if state == "active"),
        archived_scope_count=sum(1 for _, _, state in scopes if state == "archived"),
        policy=PolicyResponse(**DEFAULT_POLICY.to_dict()),
        autosnap_timer_active=_is_timer_active(),
    )


@router.get("/snapshots/scopes", response_model=list[ScopeResponse])
async def snapshot_scopes(
    project_id: str | None = None,
    include_archived: bool = False,
) -> list[ScopeResponse]:
    """List all snapshot scopes with counts and usage."""
    _, _, _, load_manifest, _, enumerate_snapshot_scopes, _ = _get_cli_libs()

    scopes = list(enumerate_snapshot_scopes(include_archived=include_archived))
    if project_id:
        scopes = [s for s in scopes if s[0] == project_id]

    results: list[ScopeResponse] = []
    for pid, scope, scope_state in scopes:
        entries = load_manifest(pid, scope)
        if not entries:
            continue
        timestamps = [e.created_at for e in entries if e.created_at]
        results.append(ScopeResponse(
            project_id=pid,
            scope_type=scope.scope_type,
            scope_name=scope.scope_name,
            scope_state=scope_state,
            snapshot_count=len(entries),
            total_bytes=None,
            newest_at=max(timestamps) if timestamps else None,
            oldest_at=min(timestamps) if timestamps else None,
        ))

    return results


@router.get("/snapshots", response_model=list[SnapshotResponse])
async def list_all_snapshots(
    project_id: str | None = None,
    scope_type: str | None = None,
    scope_name: str | None = None,
    include_archived: bool = False,
) -> list[SnapshotResponse]:
    """List all snapshots, optionally filtered by project and scope type."""
    _, _, _, load_manifest, _, enumerate_snapshot_scopes, _ = _get_cli_libs()

    scopes = list(enumerate_snapshot_scopes(include_archived=include_archived))
    if project_id:
        scopes = [s for s in scopes if s[0] == project_id]
    if scope_type:
        scopes = [s for s in scopes if s[1].scope_type == scope_type]
    if scope_name:
        scopes = [s for s in scopes if s[1].scope_name == scope_name]

    results = [_snapshot_to_response(snap) for pid, scope, _ in scopes for snap in load_manifest(pid, scope)]
    results.sort(key=lambda s: s.created_at, reverse=True)
    return results


@router.get("/snapshots/policy", response_model=PolicyResponse)
async def snapshot_policy() -> PolicyResponse:
    """Return the current autosnap retention policy."""
    from cli.lib.autosnapshot import DEFAULT_POLICY

    return PolicyResponse(**DEFAULT_POLICY.to_dict())


@router.post("/snapshots/snap", response_model=SnapshotResponse)
async def create_snapshot(req: SnapshotRequest) -> SnapshotResponse:
    """Create a manual Btrfs snapshot."""
    from cli.lib.quick_snapshots import capture_snapshot as do_capture
    from cli.lib.quick_snapshots import get_snapshot_usage
    from cli.lib.workspace_paths import get_projects_base_dir

    cwd = str(get_projects_base_dir(req.project_id))
    try:
        snap = do_capture(name=req.name, project_id=req.project_id, cwd=cwd)
    except Exception as e:
        logger.exception("snapshot_create_failed", project_id=req.project_id)
        raise HTTPException(status_code=500, detail=str(e)) from None

    usage = None
    with contextlib.suppress(Exception):
        usage = get_snapshot_usage(snap)

    return _snapshot_to_response(snap, usage)


@router.post("/snapshots/{snapshot_id}/recover")
async def recover_snap(snapshot_id: str, req: SnapshotRequest) -> dict:
    """Recover a snapshot to a sibling scope (non-destructive)."""
    from cli.lib.quick_snapshots import recover_snapshot as do_recover

    try:
        from cli.lib.workspace_paths import get_projects_base_dir
        result = do_recover(target=snapshot_id, project_id=req.project_id, name=req.name, cwd=get_projects_base_dir(req.project_id))
        return {"ok": True, "recovery_path": str(result.recovery_path) if hasattr(result, "recovery_path") else None}
    except Exception as e:
        logger.exception("snapshot_recover_failed", snapshot_id=snapshot_id)
        return {"ok": False, "error": str(e)}


@router.post("/snapshots/prune")
async def prune_snapshots(dry_run: bool | None = None, body: Annotated[dict[str, Any] | None, Body()] = None) -> dict:
    """Run retention pruning across all scopes."""
    from cli.lib.autosnapshot import DEFAULT_POLICY, LAST_PRUNE_REPORT
    from cli.lib.autosnapshot import prune_all as do_prune

    try:
        actual_dry_run = dry_run if dry_run is not None else (body or {}).get("dry_run", True)
        if not isinstance(actual_dry_run, bool):
            raise ValueError("dry_run must be a boolean")
        results = do_prune(policy=DEFAULT_POLICY, dry_run=actual_dry_run)
        return {
            "ok": True,
            "dry_run": actual_dry_run,
            "pruned": results if isinstance(results, int) else sum(len(entries) for entries in results.values()),
            "recovery_copies": list(LAST_PRUNE_REPORT),
            "recovery_copies_deleted": sum(record["action"] == "deleted" for record in LAST_PRUNE_REPORT),
            "recovery_cleanup_failed": sum(record["action"] == "failed" for record in LAST_PRUNE_REPORT),
        }
    except Exception as e:
        logger.exception("snapshot_prune_failed")
        return {"ok": False, "error": str(e)}


class RecoveryFilesRequest(BaseModel):
    project_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    paths: list[str]
    owned_paths: list[str] = []
    preview_digest: str | None = None


@router.post("/snapshots/{snapshot_id}/preview")
async def preview_selected_recovery(snapshot_id: str, req: RecoveryFilesRequest) -> dict:
    from cli.lib.quick_snapshots import recovery_preview
    from cli.lib.workspace_paths import get_projects_base_dir
    try:
        result = recovery_preview(snapshot_id, project_id=req.project_id, paths=req.paths,
            owned_paths=req.owned_paths, cwd=get_projects_base_dir(req.project_id), verify_ownership=False)
        return {"ok": True, **result, "apply_available": False,
            "apply_reason": "Apply through an ST coding session with an active own lease"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/snapshots/{snapshot_id}/apply")
async def apply_selected_recovery(snapshot_id: str, req: RecoveryFilesRequest) -> dict:
    # This HTTP surface has no authenticated native actor/claim binding. Never
    # treat client-provided ownership strings as authority to edit a shared tree.
    raise HTTPException(status_code=403, detail="Selected-file apply requires an owned ST coding session; use st recover --file --owned --preview-digest")


@router.post("/snapshots/{snapshot_id}/release")
async def release_selected_recovery(snapshot_id: str, req: SnapshotRequest) -> dict:
    from cli.lib.quick_snapshots import release_recovery
    from cli.lib.workspace_paths import get_projects_base_dir
    try:
        result = release_recovery(snapshot_id, project_id=req.project_id, cwd=get_projects_base_dir(req.project_id))
        return {"ok": True, "recovery_active": result.recovery_active, "recovery_path": result.recovery_path,
            "cleanup_pending": any(not copy.get("deleted_at") for copy in result.recovery_copies),
            "cleanup_policy": "Released copies remain until snapshot prune; failed physical deletion is retained and retried"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
