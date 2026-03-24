"""Archived task deletion snapshots for forensic retrieval."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime
from typing import Any

from psycopg import Cursor
from psycopg.types.json import Jsonb

from ..connection import get_cursor
from ..subtasks_helpers import SUBTASK_COLUMNS
from ..subtasks_helpers import row_to_dict as row_to_subtask_dict
from .columns import TASK_COLUMNS_WITH_SPIRIT
from .core import canonicalize_task_id
from .mapping import row_to_dict_with_spirit


def _jsonable(value: Any) -> Any:
    """Convert DB-backed task payloads into JSON-serializable values."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _load_task_snapshots(cur: Cursor[Any], task_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Load task + subtask snapshots for the given task ids inside one transaction."""
    if not task_ids:
        return {}

    cur.execute(
        f"""
        SELECT {TASK_COLUMNS_WITH_SPIRIT}
        FROM tasks t
        LEFT JOIN task_spirit ts ON t.id = ts.task_id
        WHERE t.id = ANY(%s)
        """,
        (task_ids,),
    )
    tasks = {
        str(task["id"]): _jsonable(task)
        for row in cur.fetchall()
        if (task := row_to_dict_with_spirit(row))
    }
    if not tasks:
        return {}

    cur.execute(
        f"""
        SELECT {SUBTASK_COLUMNS}
        FROM task_subtasks
        WHERE task_id = ANY(%s)
        ORDER BY task_id, display_order
        """,
        (list(tasks),),
    )
    subtasks_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in cur.fetchall():
        subtask = row_to_subtask_dict(row)
        task_id = str(subtask["task_id"])
        subtasks_by_task[task_id].append(_jsonable(subtask))

    return {
        task_id: {
            "task": task,
            "subtasks": subtasks_by_task.get(task_id, []),
        }
        for task_id, task in tasks.items()
    }


def archive_task_snapshots(
    cur: Cursor[Any],
    task_ids: Iterable[str],
    *,
    deletion_source: str,
    deletion_reason: str | None = None,
) -> list[str]:
    """Persist forensic task snapshots before rows are deleted."""
    resolved_ids = [canonicalize_task_id(task_id) for task_id in task_ids]
    snapshots = _load_task_snapshots(cur, resolved_ids)
    if not snapshots:
        return []

    for task_id, snapshot in snapshots.items():
        task = snapshot["task"]
        cur.execute(
            """
            INSERT INTO task_deletions (
                task_id,
                project_id,
                deletion_source,
                deletion_reason,
                snapshot
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                task_id,
                task.get("project_id"),
                deletion_source,
                deletion_reason,
                Jsonb(snapshot),
            ),
        )
    return list(snapshots)


def get_deleted_task_context(task_id: str) -> dict[str, Any] | None:
    """Return the latest archived snapshot for a deleted task."""
    resolved_task_id = canonicalize_task_id(task_id)
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT deleted_at, deletion_source, deletion_reason, snapshot
            FROM task_deletions
            WHERE task_id = %s
            ORDER BY deleted_at DESC, id DESC
            LIMIT 1
            """,
            (resolved_task_id,),
        )
        row = cur.fetchone()

    if not row:
        return None

    deleted_at, deletion_source, deletion_reason, snapshot = row
    if not isinstance(snapshot, dict):
        return None

    task = snapshot.get("task")
    if not isinstance(task, dict):
        return None

    archived_task = dict(task)
    archived_task["archived"] = True
    archived_task["deleted_at"] = deleted_at.isoformat() if deleted_at else None
    archived_task["deletion_source"] = deletion_source
    archived_task["deletion_reason"] = deletion_reason

    subtasks = snapshot.get("subtasks")
    archived_subtasks = subtasks if isinstance(subtasks, list) else []

    return {
        "task": archived_task,
        "subtasks": archived_subtasks,
        "deleted_at": archived_task["deleted_at"],
        "deletion_source": deletion_source,
        "deletion_reason": deletion_reason,
    }
