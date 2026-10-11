"""Dashboard Features/Tasks/Bugs tiles: include refactor/regression, exclude paused."""

from __future__ import annotations

from uuid import uuid4

from app.api.projects.db_helpers import fetch_project_stats
from app.storage import tasks as task_store
from app.storage.connection import get_connection


def test_tiles_count_refactor_and_regression_but_not_paused(db_schema_initialized: None) -> None:
    project_id = f"tiles-{uuid4().hex[:8]}"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO projects (id, name, base_url, category) VALUES (%s, %s, '', 'testing')",
            (project_id, "Tiles"),
        )
        conn.commit()
    try:
        made = {
            (task_type, status): task_store.create_task(project_id, f"{task_type} {status}", task_type=task_type)
            for task_type in ("feature", "task", "refactor", "bug", "regression")
            for status in ("pending", "paused")
        }
        for (_task_type, status), task in made.items():
            if status != "pending":
                task_store.update_task_status(task["id"], status, validate_transition=False)

        stats = fetch_project_stats([project_id])[project_id]

        assert (stats.features, stats.tasks, stats.bugs) == (1, 2, 2)
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM tasks WHERE project_id = %s", (project_id,))
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            conn.commit()
