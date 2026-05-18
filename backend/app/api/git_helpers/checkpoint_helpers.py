"""Checkpoint and snapshot helper functions for git operations."""

from __future__ import annotations

from psycopg import sql

from ...storage.connection import get_cursor
from ..models.git_models import CheckpointInfo, SnapshotInfo


def collect_checkpoints() -> list[CheckpointInfo]:
    """Collect active checkpoint metadata from the CLI checkpoint registry."""
    from cli.lib.checkpoint import get_active_checkpoints

    return [
        CheckpointInfo(
            task_id=checkpoint.task_id,
            base_branch=checkpoint.base_branch,
            is_active=True,
            project_id=checkpoint.project_id,
        )
        for checkpoint in get_active_checkpoints()
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
