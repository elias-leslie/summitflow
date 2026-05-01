"""Cleanup status payload builder."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cleanup_display import RepoEntry


@dataclass(frozen=True)
class CleanupStatusDeps:
    get_project_id: Callable[[bool, str | None], str | None]
    get_active_checkpoints: Callable[[str | None], Sequence[Any]]
    iter_target_repos: Callable[[bool, str | None], list[Path]]
    branch_name: Callable[[Any], str]
    workspace_summary: Callable[[Path], Any]
    stale_checkpoints: Callable[[str], Sequence[Any]]
    snapshot_residue: Callable[[str], Sequence[Any]]


def build_cleanup_status_payload_impl(
    all_projects: bool,
    *,
    project_id_override: str | None = None,
    deps: CleanupStatusDeps,
) -> dict[str, Any]:
    """Build the canonical cross-repo cleanup summary payload."""
    project_id = deps.get_project_id(all_projects, project_id_override)
    checkpoints = deps.get_active_checkpoints(project_id)
    repositories = [
        _build_repo_cleanup_entry(path, deps)
        for path in deps.iter_target_repos(all_projects, project_id_override)
    ]
    return {
        "summary": _build_summary(repositories),
        "repositories": repositories,
        "checkpoints": [
            {
                "task_id": checkpoint.task_id,
                "branch": deps.branch_name(checkpoint),
                "base_branch": checkpoint.base_branch,
                "project_id": checkpoint.project_id,
            }
            for checkpoint in checkpoints
        ],
        "total": len(checkpoints),
    }


def _build_repo_cleanup_entry(repo_path: Path, deps: CleanupStatusDeps) -> RepoEntry:
    project_id = repo_path.name
    ws = deps.workspace_summary(repo_path)
    dirty_main_repo = bool(getattr(ws, "dirty_main_repo", False))
    stale_checkpoints = len(deps.stale_checkpoints(project_id))
    snapshot_residue = len(deps.snapshot_residue(project_id))
    workspace_needs_cleanup = bool(getattr(ws, "needs_cleanup", False))
    needs_cleanup = any((
        workspace_needs_cleanup,
        stale_checkpoints,
        snapshot_residue,
    ))
    return RepoEntry(
        project_id=project_id,
        path=str(repo_path),
        active_checkpoints=ws.active_checkpoints,
        dirty_checkpoints=ws.dirty_checkpoints,
        dirty_main_repo=dirty_main_repo,
        stale_checkpoints=stale_checkpoints,
        snapshot_residue=snapshot_residue,
        orphan_task_branches=ws.orphan_branches,
        prunable_task_branches=ws.prunable_branches,
        checkpoint_task_ids=ws.checkpoint_task_ids,
        orphan_branch_names=ws.orphan_branch_names,
        prunable_branch_names=ws.prunable_branch_names,
        salvage_task_ids=ws.salvage_task_ids,
        review_orphan_task_ids=ws.review_orphan_task_ids,
        orphan_details=[detail.model_dump() for detail in ws.orphan_details],
        needs_merge_count=0,
        conflict_count=0,
        review_count=0,
        needs_merge_tasks=[],
        conflict_tasks=[],
        review_tasks=[],
        needs_cleanup=needs_cleanup,
    )


def _build_summary(repositories: list[RepoEntry]) -> dict[str, int]:
    return {
        "repos": len(repositories),
        "repos_needing_cleanup": sum(1 for repo in repositories if repo["needs_cleanup"]),
        "active_checkpoints": sum(repo["active_checkpoints"] for repo in repositories),
        "dirty_checkpoints": sum(
            int(repo["dirty_checkpoints"]) + int(bool(repo.get("dirty_main_repo")))
            for repo in repositories
        ),
        "stale_checkpoints": sum(repo["stale_checkpoints"] for repo in repositories),
        "snapshot_residue": sum(repo["snapshot_residue"] for repo in repositories),
        "orphan_task_branches": sum(repo["orphan_task_branches"] for repo in repositories),
        "prunable_task_branches": sum(repo["prunable_task_branches"] for repo in repositories),
    }
