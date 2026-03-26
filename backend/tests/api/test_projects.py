"""Tests for projects API endpoints."""

from __future__ import annotations

from uuid import uuid4

from app.storage.connection import get_connection


def test_create_project_creates_backup_source(client, monkeypatch) -> None:
    """POST /api/projects should seed a matching project backup source."""
    project_id = f"create-{uuid4().hex[:8]}"
    root_path = f"/srv/workspaces/projects/{project_id}"
    monkeypatch.setattr("app.api.projects.explorer.run_scan_job", lambda *args, **kwargs: None)

    try:
        response = client.post(
            "/api/projects",
            json={
                "id": project_id,
                "name": "Create Project",
                "base_url": "https://create.example",
                "health_endpoint": "/health",
                "root_path": root_path,
            },
        )

        assert response.status_code == 200

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, path, source_type, project_id FROM backup_sources WHERE id = %s",
                (project_id,),
            )
            row = cur.fetchone()

        assert row == (project_id, "Create Project", root_path, "project", project_id)
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM backup_sources WHERE id = %s", (project_id,))
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            conn.commit()


def test_update_project_syncs_backup_source(client) -> None:
    """PATCH /api/projects should keep the matching backup source in sync."""
    project_id = f"update-{uuid4().hex[:8]}"

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url, health_endpoint, root_path)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (project_id, "Old Name", "http://old.example", "/health", "/old/root"),
        )
        cur.execute(
            """
            INSERT INTO backup_sources (id, name, path, source_type, project_id)
            VALUES (%s, %s, %s, 'project', %s)
            """,
            (project_id, "Old Name", "/old/root", project_id),
        )
        conn.commit()

    try:
        response = client.patch(
            f"/api/projects/{project_id}",
            json={"name": "New Name", "root_path": "/new/root"},
        )

        assert response.status_code == 200

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT name, path, project_id FROM backup_sources WHERE id = %s",
                (project_id,),
            )
            row = cur.fetchone()

        assert row == ("New Name", "/new/root", project_id)
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM backup_sources WHERE id = %s", (project_id,))
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            conn.commit()


def test_list_projects_with_stats_returns_feature_task_bug_counts(client) -> None:
    """Project stats should expose distinct feature, task, and bug counts."""
    project_id = f"stats-{uuid4().hex[:8]}"
    task_ids = {
        "feature_active": f"{project_id}-feature-active",
        "feature_done": f"{project_id}-feature-done",
        "task_active": f"{project_id}-task-active",
        "task_cancelled": f"{project_id}-task-cancelled",
        "bug_active": f"{project_id}-bug-active",
        "bug_abandoned": f"{project_id}-bug-abandoned",
    }

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url, health_endpoint)
            VALUES (%s, %s, %s, %s)
            """,
            (project_id, "Stats Project", "http://localhost:3001", "/health"),
        )
        cur.execute(
            """
            INSERT INTO tasks (id, project_id, title, status, task_type)
            VALUES
              (%s, %s, %s, %s, %s),
              (%s, %s, %s, %s, %s),
              (%s, %s, %s, %s, %s),
              (%s, %s, %s, %s, %s),
              (%s, %s, %s, %s, %s),
              (%s, %s, %s, %s, %s)
            """,
            (
                task_ids["feature_active"],
                project_id,
                "Active feature",
                "pending",
                "feature",
                task_ids["feature_done"],
                project_id,
                "Completed feature",
                "completed",
                "feature",
                task_ids["task_active"],
                project_id,
                "Active task",
                "pending",
                "task",
                task_ids["task_cancelled"],
                project_id,
                "Cancelled task",
                "cancelled",
                "task",
                task_ids["bug_active"],
                project_id,
                "Active bug",
                "pending",
                "bug",
                task_ids["bug_abandoned"],
                project_id,
                "Abandoned bug",
                "abandoned",
                "bug",
            ),
        )
        conn.commit()

    try:
        response = client.get("/api/projects/with-stats")

        assert response.status_code == 200
        payload = response.json()
        project = next(item for item in payload["projects"] if item["id"] == project_id)

        assert project["stats"] == {
            "features": 1,
            "tasks": 1,
            "bugs": 1,
            "blocked": 0,
        }
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM tasks WHERE id = ANY(%s)",
                (list(task_ids.values()),),
            )
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            conn.commit()


def test_update_project_updates_selected_fields(client) -> None:
    """PATCH should update only the provided project fields."""
    project_id = f"patch-{uuid4().hex[:8]}"

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url, health_endpoint, root_path)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (project_id, "Old Name", "http://old.example", "/healthz", "/old/root"),
        )
        conn.commit()

    try:
        response = client.patch(
            f"/api/projects/{project_id}",
            json={"name": "New Name", "root_path": "/new/root"},
        )

        assert response.status_code == 200
        assert response.json()["name"] == "New Name"
        assert response.json()["root_path"] == "/new/root"
        assert response.json()["base_url"] == "http://old.example"
        assert response.json()["health_endpoint"] == "/healthz"
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            conn.commit()
