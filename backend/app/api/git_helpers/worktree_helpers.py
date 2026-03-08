"""Worktree and snapshot helper functions for git operations."""

from __future__ import annotations

from ...storage.connection import get_connection
from ..models.git_models import WorktreeInfo


def collect_worktrees() -> list[WorktreeInfo]:
    """Collect worktree info from the base directory, enriched with project_id."""
    from ....cli.lib.worktree import get_active_worktrees

    return [
        WorktreeInfo(
            task_id=worktree.task_id,
            path=str(worktree.path),
            branch=worktree.branch,
            base_branch=worktree.base_branch,
            is_active=worktree.is_active,
            project_id=worktree.project_id,
        )
        for worktree in get_active_worktrees()
    ]


def enrich_snapshots(
    snapshots: list, project_id: str | None = None,
) -> None:
    """Enrich snapshot objects with task titles from the database."""
    if not snapshots:
        return
    task_ids = [s.task_id for s in snapshots]
    placeholders = ",".join(["%s"] * len(task_ids))

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"SELECT id, title, project_id FROM tasks WHERE id IN ({placeholders})",
            tuple(task_ids),
        )
        task_map = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

    for s in snapshots:
        if s.task_id in task_map:
            s.task_title = task_map[s.task_id][0] or ""
            s.project_id = task_map[s.task_id][1] or ""
