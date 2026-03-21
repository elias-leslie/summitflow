"""Display helpers for cleanup status output."""

from __future__ import annotations

from typing import Any, TypedDict

import typer


class RepoEntry(TypedDict):
    """Typed dict for per-repo cleanup status."""

    project_id: str
    path: str
    active_worktrees: int
    dirty_worktrees: int
    stale_checkpoints: int
    snapshot_residue: int
    orphan_task_branches: int
    prunable_task_branches: int
    worktree_task_ids: list[str]
    orphan_branch_names: list[str]
    prunable_branch_names: list[str]
    salvage_task_ids: list[str]
    review_orphan_task_ids: list[str]
    needs_merge_count: int
    conflict_count: int
    review_count: int
    needs_merge_tasks: list[str]
    conflict_tasks: list[str]
    review_tasks: list[str]
    needs_cleanup: bool


def _build_attention(repo: RepoEntry) -> str:
    """Build attention string from task lists."""
    parts: list[str] = []
    for ids, label in (
        (repo["needs_merge_tasks"], "finalize"),
        (repo["conflict_tasks"], "conflicts"),
        (repo["review_tasks"], "review"),
        (repo["salvage_task_ids"], "salvage"),
        (repo["review_orphan_task_ids"], "review_orphans"),
    ):
        if ids:
            parts.append(f"{label}:{','.join(ids)}")
    return f" {' '.join(parts)}" if parts else ""


def _build_branch_preview(repo: RepoEntry) -> str:
    """Build branch preview string from branch name lists."""
    parts: list[str] = []
    if repo["prunable_branch_names"]:
        parts.append(f"prune_branches:{','.join(repo['prunable_branch_names'])}")
    if repo["orphan_branch_names"]:
        parts.append(f"orphan_branches:{','.join(repo['orphan_branch_names'])}")
    return f" {' '.join(parts)}" if parts else ""


def print_repo_compact(repo: RepoEntry) -> None:
    """Print compact status line for one repo entry."""
    if not repo["needs_cleanup"] and not repo["active_worktrees"]:
        print(f"{repo['project_id']} clean")
        return
    preview = f" tasks:{','.join(repo['worktree_task_ids'])}" if repo["worktree_task_ids"] else ""
    stale = f" stale_cp:{repo['stale_checkpoints']}" if repo["stale_checkpoints"] else ""
    snap = f" snap:{repo['snapshot_residue']}" if repo["snapshot_residue"] else ""
    print(
        f"{repo['project_id']} worktrees:{repo['active_worktrees']} "
        f"dirty:{repo['dirty_worktrees']}{stale}{snap} "
        f"orphan:{repo['orphan_task_branches']} "
        f"prunable:{repo['prunable_task_branches']}{preview}"
        f"{_build_attention(repo)}{_build_branch_preview(repo)}"
    )


def format_cleanup_status_compact(data: dict[str, Any], all_projects: bool) -> None:
    """Emit TOON summary for cleanup status."""
    summary = data["summary"]
    assert isinstance(summary, dict)
    scope = "all" if all_projects else "current"
    print(
        "CLEANUP[{scope}]:repos={repos} needs_cleanup={needs} worktrees={worktrees} "
        "dirty={dirty} stale_cp={stale_cp} snap={snap} orphan={orphan} prunable={prunable}".format(
            scope=scope,
            repos=summary["repos"],
            needs=summary["repos_needing_cleanup"],
            worktrees=summary["active_worktrees"],
            dirty=summary["dirty_worktrees"],
            stale_cp=summary["stale_checkpoints"],
            snap=summary["snapshot_residue"],
            orphan=summary["orphan_task_branches"],
            prunable=summary["prunable_task_branches"],
        )
    )
    repositories = data["repositories"]
    assert isinstance(repositories, list)
    for repo in repositories:
        print_repo_compact(repo)


def print_git_residue_report(
    pruned_registrations: int,
    pruned_merged: int,
    pruned_equivalent: int,
    pruned_closed: int,
) -> None:
    """Print pruned git residue counts."""
    typer.echo(f"  Pruned git worktree registrations in {pruned_registrations} repo(s)")
    typer.echo(f"  Pruned merged orphan task branches: {pruned_merged}")
    typer.echo(f"  Pruned equivalent orphan task branches: {pruned_equivalent}")
    typer.echo(f"  Pruned closed orphan task branches: {pruned_closed}")
