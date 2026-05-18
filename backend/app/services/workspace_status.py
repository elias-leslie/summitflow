"""Shared workspace hygiene summaries for project coordination surfaces."""

from __future__ import annotations

from typing import Any

from cli.commands.cleanup import build_cleanup_status_payload


def build_project_cleanup_status(project_id: str) -> dict[str, Any]:
    """Return cleanup/checkpoint summary for one managed repository."""
    payload = build_cleanup_status_payload(False, project_id_override=project_id)
    repositories = payload.get("repositories") or []
    repo_entry = repositories[0] if repositories else None
    if not isinstance(repo_entry, dict):
        return {
            "project_id": project_id,
            "path": None,
            "active_checkpoints": 0,
            "dirty_checkpoints": 0,
            "dirty_main_repo": False,
            "stale_checkpoints": 0,
            "snapshot_residue": 0,
            "needs_merge_count": 0,
            "conflict_count": 0,
            "review_count": 0,
            "checkpoint_task_ids": [],
            "needs_cleanup": False,
        }

    dirty_total = int(repo_entry.get("dirty_checkpoints") or 0) + int(
        bool(repo_entry.get("dirty_main_repo"))
    )
    return {
        "project_id": project_id,
        "path": repo_entry.get("path"),
        "active_checkpoints": int(repo_entry.get("active_checkpoints") or 0),
        "dirty_checkpoints": dirty_total,
        "dirty_main_repo": bool(repo_entry.get("dirty_main_repo")),
        "stale_checkpoints": int(repo_entry.get("stale_checkpoints") or 0),
        "snapshot_residue": int(repo_entry.get("snapshot_residue") or 0),
        "needs_merge_count": int(repo_entry.get("needs_merge_count") or 0),
        "conflict_count": int(repo_entry.get("conflict_count") or 0),
        "review_count": int(repo_entry.get("review_count") or 0),
        "checkpoint_task_ids": list(repo_entry.get("checkpoint_task_ids") or []),
        "needs_cleanup": bool(repo_entry.get("needs_cleanup")),
    }
