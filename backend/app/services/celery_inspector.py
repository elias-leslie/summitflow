"""Celery task inspection service for SummitFlow.

Provides functions to inspect Celery tasks from multiple sources:
- Active tasks (currently running)
- Pending tasks (queued/reserved)
- Completed tasks (from celery_taskmeta table)
- Failed tasks (from celery_taskmeta table)
"""

from __future__ import annotations

import json
import pickle
from datetime import UTC, datetime
from typing import Any, Literal

from app.celery_app import celery_app
from app.storage.connection import get_connection


def _deserialize_celery_field(value: Any) -> str | None:
    """Safely deserialize a Celery result/traceback field.

    Celery stores results/tracebacks as pickled objects in bytea columns.
    When read from the database, they come back as memoryview objects.

    Args:
        value: Raw field value from database (memoryview, bytes, or already deserialized)

    Returns:
        JSON-serializable string representation, or None if empty/invalid
    """
    if value is None:
        return None

    try:
        # Convert memoryview to bytes
        bytes_value = value.tobytes() if isinstance(value, memoryview) else value

        # If it's bytes, try to unpickle
        if isinstance(bytes_value, bytes):
            try:
                unpickled = pickle.loads(bytes_value)
                return (
                    json.dumps(unpickled) if isinstance(unpickled, dict | list) else str(unpickled)
                )
            except (pickle.UnpicklingError, Exception):
                try:
                    return bytes_value.decode("utf-8")
                except UnicodeDecodeError:
                    return f"<binary data: {len(bytes_value)} bytes>"

        return str(value)

    except Exception as e:
        return f"<error deserializing: {e!s}>"


def get_active_tasks() -> list[dict[str, Any]]:
    """Get currently running tasks from Celery workers.

    Returns:
        List of active tasks with normalized schema
    """
    inspect = celery_app.control.inspect(timeout=2.0)
    try:
        active = inspect.active()

        if not active:
            return []

        tasks: list[dict[str, Any]] = []
        for worker_name, worker_tasks in active.items():
            for task in worker_tasks:
                args = task.get("args", [])
                kwargs = task.get("kwargs", {})
                args_str = json.dumps(args) if isinstance(args, list | tuple) else str(args)
                kwargs_str = json.dumps(kwargs) if isinstance(kwargs, dict) else str(kwargs)

                normalized_task = {
                    "id": task["id"],
                    "name": task["name"],
                    "status": "ACTIVE",
                    "started_at": (
                        datetime.fromtimestamp(task["time_start"]).isoformat()
                        if "time_start" in task
                        else None
                    ),
                    "duration": (
                        (datetime.now(UTC).timestamp() - task["time_start"])
                        if "time_start" in task
                        else None
                    ),
                    "worker": worker_name,
                    "args": args_str,
                    "kwargs": kwargs_str,
                }
                tasks.append(normalized_task)

        return tasks
    finally:
        if hasattr(inspect, "close"):
            inspect.close()


def get_pending_tasks() -> list[dict[str, Any]]:
    """Get pending/reserved tasks from Celery workers.

    Returns:
        List of pending tasks with normalized schema
    """
    inspect = celery_app.control.inspect(timeout=2.0)
    try:
        reserved = inspect.reserved()

        if not reserved:
            return []

        tasks: list[dict[str, Any]] = []
        for worker_name, worker_tasks in reserved.items():
            for task in worker_tasks:
                args = task.get("args", [])
                kwargs = task.get("kwargs", {})
                args_str = json.dumps(args) if isinstance(args, list | tuple) else str(args)
                kwargs_str = json.dumps(kwargs) if isinstance(kwargs, dict) else str(kwargs)

                normalized_task = {
                    "id": task["id"],
                    "name": task["name"],
                    "status": "PENDING",
                    "started_at": None,
                    "duration": None,
                    "worker": worker_name,
                    "args": args_str,
                    "kwargs": kwargs_str,
                }
                tasks.append(normalized_task)

        return tasks
    finally:
        if hasattr(inspect, "close"):
            inspect.close()


def get_recent_completed(limit: int = 50) -> list[dict[str, Any]]:
    """Get recently completed tasks from celery_taskmeta table.

    Args:
        limit: Maximum number of tasks to return (default 50)

    Returns:
        List of completed tasks with normalized schema
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                SELECT task_id, status, result, date_done, traceback, name, args, kwargs, worker
                FROM celery_taskmeta
                WHERE status = 'SUCCESS'
                ORDER BY date_done DESC
                LIMIT %s
                """,
            [limit],
        )
        rows = cur.fetchall()

        tasks = []
        for row in rows:
            task = {
                "task_id": row[0],
                "status": row[1],
                "result": _deserialize_celery_field(row[2]),
                "date_done": row[3].isoformat() if isinstance(row[3], datetime) else None,
                "traceback": _deserialize_celery_field(row[4]),
                "name": row[5] or "unknown",
                "args": _deserialize_celery_field(row[6]),
                "kwargs": _deserialize_celery_field(row[7]),
                "worker": row[8],
            }
            tasks.append(task)

        return tasks


def get_recent_failed(limit: int = 50) -> list[dict[str, Any]]:
    """Get recently failed tasks from celery_taskmeta table.

    Args:
        limit: Maximum number of tasks to return (default 50)

    Returns:
        List of failed tasks with normalized schema
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
                SELECT task_id, status, result, date_done, traceback, name, args, kwargs, worker
                FROM celery_taskmeta
                WHERE status = 'FAILURE'
                ORDER BY date_done DESC
                LIMIT %s
                """,
            [limit],
        )
        rows = cur.fetchall()

        tasks = []
        for row in rows:
            task = {
                "task_id": row[0],
                "status": row[1],
                "result": _deserialize_celery_field(row[2]),
                "date_done": row[3].isoformat() if isinstance(row[3], datetime) else None,
                "traceback": _deserialize_celery_field(row[4]),
                "name": row[5] or "unknown",
                "args": _deserialize_celery_field(row[6]),
                "kwargs": _deserialize_celery_field(row[7]),
                "worker": row[8],
            }
            tasks.append(task)

        return tasks


def get_queue_depth() -> int:
    """Get total count of pending/queued tasks across all workers.

    Returns:
        Total number of pending tasks
    """
    pending_tasks = get_pending_tasks()
    return len(pending_tasks)


def get_worker_stats() -> dict[str, Any]:
    """Get worker statistics.

    Returns:
        Dict with worker count and basic stats
    """
    inspect = celery_app.control.inspect(timeout=2.0)
    try:
        stats = inspect.stats()
        if not stats:
            return {"workers": 0, "details": {}}

        return {
            "workers": len(stats),
            "details": {
                name: {
                    "concurrency": s.get("pool", {}).get("max-concurrency", 0),
                    "running": len(s.get("pool", {}).get("writes", {}).get("active", [])),
                }
                for name, s in stats.items()
            },
        }
    finally:
        if hasattr(inspect, "close"):
            inspect.close()


def get_unified_task_list(
    status: Literal["all", "active", "pending", "completed", "failed"] = "all",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Get unified task list from all sources with optional filtering.

    Args:
        status: Filter by task status
        limit: Maximum number of tasks to return per category

    Returns:
        List of tasks from all sources
    """
    tasks: list[dict[str, Any]] = []

    if status in ("all", "active"):
        tasks.extend(get_active_tasks())

    if status in ("all", "pending"):
        tasks.extend(get_pending_tasks())

    if status in ("all", "completed"):
        completed = get_recent_completed(limit=limit)
        for task in completed:
            task["id"] = task.pop("task_id")
            task["started_at"] = None
            task["duration"] = None
        tasks.extend(completed)

    if status in ("all", "failed"):
        failed = get_recent_failed(limit=limit)
        for task in failed:
            task["id"] = task.pop("task_id")
            task["started_at"] = None
            task["duration"] = None
        tasks.extend(failed)

    return tasks
