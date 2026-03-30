"""Tests for projects API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import HTTPException

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


def test_create_project_syncs_agent_hub_permission_when_requested(client, monkeypatch) -> None:
    """POST /api/projects should provision Agent Hub permission bootstrap when requested."""
    project_id = f"bootstrap-{uuid4().hex[:8]}"
    root_path = f"/srv/workspaces/projects/{project_id}"
    sync_mock = AsyncMock()
    monkeypatch.setattr("app.api.projects.explorer.run_scan_job", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.api.projects.sync_agent_hub_project_permission", sync_mock)

    try:
        response = client.post(
            "/api/projects",
            json={
                "id": project_id,
                "name": "Bootstrap Project",
                "base_url": "https://bootstrap.example",
                "health_endpoint": "/health",
                "root_path": root_path,
                "agent_hub_permission": {
                    "permission_tier": "yolo",
                    "auto_exec_enabled": True,
                    "execution_start_hour": 0,
                    "execution_end_hour": 24,
                },
            },
        )

        assert response.status_code == 200
        sync_mock.assert_awaited_once()
        args = sync_mock.await_args.args
        assert args[0] == project_id
        assert args[1].permission_tier == "yolo"
        assert args[1].auto_exec_enabled is True
        assert args[2] == root_path
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM backup_sources WHERE id = %s", (project_id,))
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            conn.commit()


def test_create_project_queues_standard_onboarding_when_requested(client, monkeypatch) -> None:
    """POST /api/projects should use the shared onboarding flow when requested."""
    project_id = f"onboard-{uuid4().hex[:8]}"
    root_path = f"/srv/workspaces/projects/{project_id}"
    onboarding_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    monkeypatch.setattr(
        "app.api.projects.run_project_onboarding",
        lambda *args, **kwargs: onboarding_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "app.api.projects.explorer.run_scan_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("raw scan should not be queued")),
    )

    try:
        response = client.post(
            "/api/projects",
            json={
                "id": project_id,
                "name": "Onboarded Project",
                "base_url": "https://onboard.example",
                "health_endpoint": "/health",
                "root_path": root_path,
                "onboarding": {
                    "backup_frequency": "daily",
                    "backup_retention_days": 30,
                    "queue_initial_backup": True,
                },
            },
        )

        assert response.status_code == 200
        assert len(onboarding_calls) == 1
        args, kwargs = onboarding_calls[0]
        assert args[0] == project_id
        assert args[1].backup_frequency == "daily"
        assert args[1].backup_retention_days == 30
        assert kwargs["triggered_by"] == "project_create"
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM backup_sources WHERE id = %s", (project_id,))
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            conn.commit()


def test_create_project_rolls_back_when_agent_hub_sync_fails(client, monkeypatch) -> None:
    """POST /api/projects should remove the project record when bootstrap sync fails."""
    project_id = f"rollback-{uuid4().hex[:8]}"
    root_path = f"/srv/workspaces/projects/{project_id}"

    async def _fail_sync(*_args, **_kwargs) -> None:
        raise HTTPException(status_code=502, detail="Agent Hub unavailable")

    monkeypatch.setattr("app.api.projects.explorer.run_scan_job", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.api.projects.sync_agent_hub_project_permission", _fail_sync)

    response = client.post(
        "/api/projects",
        json={
            "id": project_id,
            "name": "Rollback Project",
            "base_url": "https://rollback.example",
            "health_endpoint": "/health",
            "root_path": root_path,
            "agent_hub_permission": {
                "permission_tier": "yolo",
                "auto_exec_enabled": True,
                "execution_start_hour": 0,
                "execution_end_hour": 24,
            },
        },
    )

    assert response.status_code == 502
    assert response.json()["message"] == "Agent Hub unavailable"

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        project_row = cur.fetchone()
        cur.execute("SELECT id FROM backup_sources WHERE id = %s", (project_id,))
        backup_row = cur.fetchone()

    assert project_row is None
    assert backup_row is None


def test_onboard_project_queues_standard_onboarding(client, monkeypatch) -> None:
    """POST /api/projects/{project_id}/onboard should queue the shared onboarding helper."""
    project_id = f"manual-onboard-{uuid4().hex[:8]}"
    root_path = f"/srv/workspaces/projects/{project_id}"
    onboarding_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url, health_endpoint, root_path)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (project_id, "Manual Onboard", "https://manual.example", "/health", root_path),
        )
        cur.execute(
            """
            INSERT INTO backup_sources (id, name, path, source_type, project_id)
            VALUES (%s, %s, %s, 'project', %s)
            """,
            (project_id, "Manual Onboard", root_path, project_id),
        )
        conn.commit()

    monkeypatch.setattr(
        "app.api.projects.run_project_onboarding",
        lambda *args, **kwargs: onboarding_calls.append((args, kwargs)),
    )

    try:
        response = client.post(
            f"/api/projects/{project_id}/onboard",
            json={
                "backup_frequency": "daily",
                "backup_retention_days": 30,
                "queue_initial_backup": True,
            },
        )

        assert response.status_code == 200
        assert response.json() == {
            "status": "queued",
            "project_id": project_id,
            "backup_schedule_enabled": True,
            "backup_frequency": "daily",
            "backup_retention_days": 30,
            "queue_initial_backup": True,
        }
        assert len(onboarding_calls) == 1
        args, kwargs = onboarding_calls[0]
        assert args[0] == project_id
        assert args[1].backup_frequency == "daily"
        assert args[1].backup_retention_days == 30
        assert kwargs["triggered_by"] == "project_onboard"
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM backup_sources WHERE id = %s", (project_id,))
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            conn.commit()


def test_run_project_onboarding_seeds_backup_schedule_anchor(monkeypatch) -> None:
    """Onboarding should seed the first scheduled run after queuing a baseline backup."""
    from app.api.projects.models import ProjectOnboardingRequest
    from app.api.projects.onboarding import run_project_onboarding

    update_source_last_run = MagicMock()

    monkeypatch.setattr(
        "app.api.projects.onboarding.get_project_root_path",
        lambda _project_id: "/srv/workspaces/projects/vantage",
    )
    monkeypatch.setattr(
        "app.api.projects.onboarding.backup_store.get_source",
        lambda _project_id: {"id": "vantage", "last_run_at": None},
    )
    monkeypatch.setattr(
        "app.api.projects.onboarding.backup_store.update_source",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "app.api.projects.onboarding.backup_store.list_backups",
        lambda **_kwargs: ([], 0),
    )
    monkeypatch.setattr(
        "app.api.projects.onboarding.backup_store.get_latest_backup",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "app.api.projects.onboarding._queue_initial_backup",
        lambda _project_id: None,
    )
    monkeypatch.setattr(
        "app.api.projects.onboarding.backup_store.update_source_last_run",
        update_source_last_run,
    )
    monkeypatch.setattr(
        "app.api.projects.onboarding.explorer.run_scan_job",
        lambda *_args, **_kwargs: {"scan_id": 7},
    )
    monkeypatch.setattr(
        "app.api.projects.onboarding.dispatch_post_scan_tasks",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "app.api.projects.onboarding._make_dispatch_callback",
        lambda: None,
    )

    run_project_onboarding(
        "vantage",
        ProjectOnboardingRequest(),
        triggered_by="project_onboard",
    )

    update_source_last_run.assert_called_once()
    args = update_source_last_run.call_args.args
    assert args[0] == "vantage"
    assert args[1] is not None


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


def test_list_projects_with_stats_returns_feature_task_bug_counts(
    client,
    monkeypatch,
) -> None:
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
        async def _healthy_statuses(projects):
            return {project[0]: "healthy" for project in projects}

        monkeypatch.setattr(
            "app.api.projects._resolve_project_health_statuses",
            _healthy_statuses,
        )
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
        assert project["health_status"] == "healthy"
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM tasks WHERE id = ANY(%s)",
                (list(task_ids.values()),),
            )
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            conn.commit()


def test_list_projects_includes_live_health_status(client, monkeypatch) -> None:
    """Project list responses should include live health labels for selectors/sidebar."""
    project_id = f"health-{uuid4().hex[:8]}"

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url, health_endpoint)
            VALUES (%s, %s, %s, %s)
            """,
            (project_id, "Health Project", "http://localhost:3999", "/health"),
        )
        conn.commit()

    async def _warning_statuses(projects):
        return {project[0]: "warning" for project in projects}

    monkeypatch.setattr(
        "app.api.projects._resolve_project_health_statuses",
        _warning_statuses,
    )

    try:
        response = client.get("/api/projects")

        assert response.status_code == 200
        project = next(item for item in response.json() if item["id"] == project_id)
        assert project["health_status"] == "warning"
    finally:
        with get_connection() as conn, conn.cursor() as cur:
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


def test_delete_project_removes_backup_source_and_agent_hub_permission(client, monkeypatch) -> None:
    """DELETE /api/projects should clean up backup metadata and Agent Hub permission."""
    project_id = f"delete-{uuid4().hex[:8]}"
    delete_mock = AsyncMock()

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url, health_endpoint, root_path)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                project_id,
                "Delete Project",
                "https://delete.example",
                "/health",
                f"/srv/workspaces/projects/{project_id}",
            ),
        )
        cur.execute(
            """
            INSERT INTO backup_sources (id, name, path, source_type, project_id)
            VALUES (%s, %s, %s, 'project', %s)
            """,
            (
                project_id,
                "Delete Project",
                f"/srv/workspaces/projects/{project_id}",
                project_id,
            ),
        )
        conn.commit()

    monkeypatch.setattr("app.api.projects.delete_agent_hub_project_permission", delete_mock)

    response = client.delete(f"/api/projects/{project_id}")

    assert response.status_code == 200
    delete_mock.assert_awaited_once_with(project_id)
    assert response.json() == {"status": "deleted", "project_id": project_id}

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
        project_row = cur.fetchone()
        cur.execute("SELECT id FROM backup_sources WHERE id = %s", (project_id,))
        backup_row = cur.fetchone()

    assert project_row is None
    assert backup_row is None
