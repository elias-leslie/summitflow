"""Worktree and snapshot helper functions for git operations."""

from __future__ import annotations

from psycopg import sql

from ...storage.connection import get_cursor
from ..models.git_models import SnapshotInfo, WorktreeInfo


def collect_worktrees() -> list[WorktreeInfo]:
    """Collect worktree info from the CLI worktree registry."""
    from cli.lib.worktree import get_active_worktrees

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


def enrich_snapshots(snapshots: list[SnapshotInfo]) -> None:
    """Enrich snapshot objects with task titles from the database."""
    if not snapshots:
        return
    task_ids = [s.task_id for s in snapshots]
    placeholders = sql.SQL(",").join(sql.Placeholder() for _ in task_ids)
    query = sql.SQL(
        "SELECT id, title, project_id FROM tasks WHERE id IN ({placeholders})"
    ).format(placeholders=placeholders)

    with get_cursor() as cur:
        cur.execute(query, tuple(task_ids))
        task_map = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

    for s in snapshots:
        if s.task_id in task_map:
            s.task_title = task_map[s.task_id][0] or ""
            s.project_id = task_map[s.task_id][1] or ""
