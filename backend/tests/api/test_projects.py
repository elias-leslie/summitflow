"""Tests for projects API endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.projects.public_urls import clear_public_url_config_cache, resolve_project_public_url
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
            cur.execute(
                "SELECT category, sidebar_rank FROM projects WHERE id = %s",
                (project_id,),
            )
            project_row = cur.fetchone()

        assert row == (project_id, "Create Project", root_path, "project", project_id)
        assert project_row == ("dev", None)
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM backup_sources WHERE id = %s", (project_id,))
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            conn.commit()


def test_get_project_services_returns_manifest_derived_config(client, monkeypatch) -> None:
    """GET /api/projects/{id}/services should expose worktree runtime config."""
    monkeypatch.setattr(
        "app.api.projects.load_project_worktree_services_dict",
        lambda project_id: {
            "config_source": "project_identity",
            "services": {
                "backend": {
                    "name": "backend",
                    "command": "uvicorn app.main:app --port ${PORT}",
                    "port": 8003,
                    "worktree_port_base": 8100,
                    "worktree_port_range": 100,
                    "cwd": "backend",
                    "env_files": [],
                    "environment": {"AGENT_HUB_PORT": "${SF_WORKTREE_BACKEND_PORT}"},
                    "build_command": None,
                    "install_command": None,
                }
            },
        },
    )

    response = client.get("/api/projects/agent-hub/services")

    assert response.status_code == 200
    assert response.json()["config_source"] == "project_identity"
    assert response.json()["services"]["backend"]["cwd"] == "backend"


def test_get_project_services_returns_404_for_unknown_manifest(client, monkeypatch) -> None:
    """GET /api/projects/{id}/services should report missing manifest clearly."""
    monkeypatch.setattr(
        "app.api.projects.load_project_worktree_services_dict",
        lambda project_id: (_ for _ in ()).throw(ValueError(f"Project identity manifest not found for {project_id}")),
    )

    response = client.get("/api/projects/missing-project/services")

    assert response.status_code == 404
    assert "Project identity manifest not found for missing-project" in response.text


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
                "category": "testing",
                "agent_hub_permission": {
                    "permission_tier": "yolo",
                    "auto_exec_enabled": True,
                    "execution_start_hour": 0,
                    "execution_end_hour": 24,
                },
            },
        )

        assert response.status_code == 200
        assert response.json()["category"] == "testing"
        sync_mock.assert_awaited_once()
        assert sync_mock.await_args is not None
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


@pytest.mark.asyncio
async def test_reconcile_agent_hub_project_identity_renames_legacy_permission(monkeypatch) -> None:
    """Legacy Agent Hub permission ids should be recreated under the canonical project id."""
    from app.api.projects.agent_hub import reconcile_agent_hub_project_identity

    fetch_calls: list[str] = []
    sync_mock = AsyncMock()
    delete_mock = AsyncMock()

    async def fake_fetch(project_id: str):
        fetch_calls.append(project_id)
        if project_id == "terminal":
            return {
                "project_id": "terminal",
                "permission_tier": "read",
                "auto_exec_enabled": True,
                "execution_start_hour": 2,
                "execution_end_hour": 20,
                "root_path": "/srv/workspaces/projects/legacy-a-term",
                "daily_cost_budget_usd": 5.0,
                "monthly_cost_budget_usd": 50.0,
                "budget_alert_threshold": 0.9,
            }
        return None

    monkeypatch.setattr("app.api.projects.agent_hub._fetch_agent_hub_project_permission", fake_fetch)
    monkeypatch.setattr("app.api.projects.agent_hub.sync_agent_hub_project_permission", sync_mock)
    monkeypatch.setattr("app.api.projects.agent_hub.delete_agent_hub_project_permission", delete_mock)

    await reconcile_agent_hub_project_identity(
        requested_project_id="a-term",
        canonical_project_id="a-term",
        aliases=("a-term", "aterm", "terminal"),
        root_path="/srv/workspaces/projects/a-term",
    )

    assert fetch_calls == ["a-term", "aterm", "terminal"]
    sync_mock.assert_awaited_once()
    assert sync_mock.await_args is not None
    sync_args = sync_mock.await_args.args
    assert sync_args[0] == "a-term"
    assert sync_args[1].permission_tier == "read"
    assert sync_args[1].auto_exec_enabled is True
    assert sync_args[1].execution_start_hour == 2
    assert sync_args[1].execution_end_hour == 20
    assert sync_args[1].root_path == "/srv/workspaces/projects/a-term"
    assert sync_args[1].daily_cost_budget_usd == 5.0
    assert sync_args[1].monthly_cost_budget_usd == 50.0
    assert sync_args[1].budget_alert_threshold == 0.9
    assert sync_args[2] == "/srv/workspaces/projects/a-term"
    assert [call.args[0] for call in delete_mock.await_args_list] == ["aterm", "terminal"]


def test_create_project_queues_standard_onboarding_when_requested(client, monkeypatch) -> None:
    """POST /api/projects should use the shared onboarding flow when requested."""
    project_id = f"onboard-{uuid4().hex[:8]}"
    root_path = f"/srv/workspaces/projects/{project_id}"
    onboarding_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

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
        request = cast(Any, args[1])
        assert request.backup_frequency == "daily"
        assert request.backup_retention_days == 30
        assert kwargs["triggered_by"] == "project_create"
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM backup_sources WHERE id = %s", (project_id,))
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            conn.commit()


def test_create_project_prefers_manifest_display_name(client, monkeypatch, tmp_path) -> None:
    """POST /api/projects should use manifest display names when available."""
    project_id = f"manifest-{uuid4().hex[:8]}"
    root_path = tmp_path / project_id
    root_path.mkdir()
    (root_path / "project.identity.json").write_text(
        json.dumps(
            {
                "project": {
                    "id": project_id,
                    "display_name": "A-Term Preview",
                }
            }
        )
    )
    monkeypatch.setattr("app.api.projects.explorer.run_scan_job", lambda *args, **kwargs: None)

    try:
        response = client.post(
            "/api/projects",
            json={
                "id": project_id,
                "name": "Old A-Term Name",
                "base_url": "https://a-term.example",
                "health_endpoint": "/health",
                "root_path": str(root_path),
            },
        )

        assert response.status_code == 200
        assert response.json()["name"] == "A-Term Preview"

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT name FROM projects WHERE id = %s", (project_id,))
            project_name = cur.fetchone()
            cur.execute("SELECT name FROM backup_sources WHERE id = %s", (project_id,))
            backup_name = cur.fetchone()

        assert project_name == ("A-Term Preview",)
        assert backup_name == ("A-Term Preview",)
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM backup_sources WHERE id = %s", (project_id,))
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            conn.commit()


def test_get_project_prefers_manifest_display_name_for_existing_rows(client, tmp_path) -> None:
    """GET /api/projects/{id} should overlay manifest display names over stale DB values."""
    project_id = f"existing-{uuid4().hex[:8]}"
    root_path = tmp_path / project_id
    root_path.mkdir()
    (root_path / "project.identity.json").write_text(
        json.dumps(
            {
                "project": {
                    "id": project_id,
                    "display_name": "A-Term",
                }
            }
        )
    )

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url, health_endpoint, root_path)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (project_id, "SummitFlow A-Term", "https://old.example", "/health", str(root_path)),
        )
        conn.commit()

    try:
        response = client.get(f"/api/projects/{project_id}")

        assert response.status_code == 200
        assert response.json()["name"] == "A-Term"
    finally:
        with get_connection() as conn, conn.cursor() as cur:
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
    onboarding_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

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
        request = cast(Any, args[1])
        assert request.backup_frequency == "daily"
        assert request.backup_retention_days == 30
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


def test_update_project_clears_stale_public_url_when_hosting_is_removed(client) -> None:
    """PATCH /api/projects should clear stored public URLs that no longer apply."""
    project_id = f"public-clear-{uuid4().hex[:8]}"
    original_root = f"/srv/workspaces/projects/{project_id}"

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url, public_url, health_endpoint, root_path)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                project_id,
                "Hosted Project",
                "http://localhost:3999",
                f"https://{project_id}.example.test",
                "/health",
                original_root,
            ),
        )
        conn.commit()

    try:
        response = client.patch(
            f"/api/projects/{project_id}",
            json={"root_path": f"/tmp/{project_id}"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["public_url"] == "http://localhost:3999"

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT public_url, root_path FROM projects WHERE id = %s", (project_id,))
            row = cur.fetchone()

        assert row == (None, f"/tmp/{project_id}")
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            conn.commit()


def test_resolve_project_public_url_uses_alias_for_hosted_local_project(monkeypatch) -> None:
    """Hosted workspace projects should expose their canonical public alias."""
    clear_public_url_config_cache()
    monkeypatch.setenv("SUMMITFLOW_PROJECT_PUBLIC_BASE_DOMAIN", "example.test")
    monkeypatch.setenv("SUMMITFLOW_PROJECT_PUBLIC_HOST_ALIASES", '{"monkey-fight":"mf"}')
    assert (
        resolve_project_public_url(
            "monkey-fight",
            base_url="http://localhost:4001",
            public_url=None,
            root_path="/srv/workspaces/projects/monkey-fight",
        )
        == "https://mf.example.test"
    )
    clear_public_url_config_cache()


def test_resolve_project_public_url_preserves_public_base_url() -> None:
    """External public URLs should stay user-facing when already configured."""
    assert (
        resolve_project_public_url(
            "external-demo",
            base_url="https://demo.example.com/",
            public_url=None,
            root_path="/opt/projects/external-demo",
        )
        == "https://demo.example.com"
    )


def test_get_project_returns_public_url_for_workspace_project(client, monkeypatch) -> None:
    """GET /api/projects/{id} should expose the canonical public app URL."""
    project_id = f"hosted-{uuid4().hex[:8]}"
    root_path = f"/srv/workspaces/projects/{project_id}"
    monkeypatch.setenv("SUMMITFLOW_PROJECT_PUBLIC_BASE_DOMAIN", "example.test")
    monkeypatch.delenv("SUMMITFLOW_PROJECT_PUBLIC_HOST_ALIASES", raising=False)
    clear_public_url_config_cache()

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url, health_endpoint, root_path)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (project_id, "Hosted Project", "http://localhost:3999", "/health", root_path),
        )
        conn.commit()

    async def _warning_statuses(projects):
        return {project[0]: "warning" for project in projects}

    monkeypatch.setattr(
        "app.api.projects._resolve_project_health_statuses",
        _warning_statuses,
    )

    try:
        response = client.get(f"/api/projects/{project_id}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["base_url"] == "http://localhost:3999"
        assert payload["public_url"] == f"https://{project_id}.example.test"
        assert payload["health_status"] == "warning"
    finally:
        clear_public_url_config_cache()
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            conn.commit()


def test_create_project_derives_hosted_urls_from_private_config(client, monkeypatch) -> None:
    """POST /api/projects should derive hosted URLs without baking domains into code."""
    project_id = f"hosted-create-{uuid4().hex[:8]}"
    root_path = f"/srv/workspaces/projects/{project_id}"
    monkeypatch.setenv("SUMMITFLOW_PROJECT_PUBLIC_BASE_DOMAIN", "example.test")
    monkeypatch.delenv("SUMMITFLOW_PROJECT_PUBLIC_HOST_ALIASES", raising=False)
    monkeypatch.setattr("app.api.projects.explorer.run_scan_job", lambda *args, **kwargs: None)
    clear_public_url_config_cache()

    try:
        response = client.post(
            "/api/projects",
            json={
                "id": project_id,
                "name": "Hosted Create",
                "root_path": root_path,
                "summitflow_hosted": True,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["base_url"] == f"https://{project_id}.example.test"
        assert payload["public_url"] == f"https://{project_id}.example.test"
    finally:
        clear_public_url_config_cache()
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
        assert project["category"] == "dev"
        assert project["sidebar_rank"] is None
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
            json={
                "name": "New Name",
                "root_path": "/new/root",
                "category": "production",
                "sidebar_rank": 2,
            },
        )

        assert response.status_code == 200
        assert response.json()["name"] == "New Name"
        assert response.json()["root_path"] == "/new/root"
        assert response.json()["base_url"] == "http://old.example"
        assert response.json()["health_endpoint"] == "/healthz"
        assert response.json()["category"] == "production"
        assert response.json()["sidebar_rank"] == 2
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            conn.commit()


def test_list_projects_orders_by_category_rank_then_name(client, monkeypatch) -> None:
    """Project list should group by category, then sidebar rank, then name."""
    project_prefix = uuid4().hex[:8]
    project_rows = [
        (f"{project_prefix}-alpha", "Alpha", "production", None),
        (f"{project_prefix}-bravo", "Bravo", "production", 0),
        (f"{project_prefix}-delta", "Delta", "testing", None),
        (f"{project_prefix}-charlie", "Charlie", "testing", 1),
        (f"{project_prefix}-echo", "Echo", "dev", None),
    ]

    with get_connection() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO projects (id, name, base_url, health_endpoint, category, sidebar_rank)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    project_id,
                    name,
                    f"https://{project_id}.example",
                    "/health",
                    category,
                    sidebar_rank,
                )
                for project_id, name, category, sidebar_rank in project_rows
            ],
        )
        conn.commit()

    async def _healthy_statuses(projects):
        return {project[0]: "healthy" for project in projects}

    monkeypatch.setattr(
        "app.api.projects._resolve_project_health_statuses",
        _healthy_statuses,
    )

    try:
        response = client.get("/api/projects")

        assert response.status_code == 200
        filtered = [
            project["id"]
            for project in response.json()
            if project["id"] in {row[0] for row in project_rows}
        ]
        assert filtered == [
            f"{project_prefix}-bravo",
            f"{project_prefix}-alpha",
            f"{project_prefix}-charlie",
            f"{project_prefix}-delta",
            f"{project_prefix}-echo",
        ]
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM projects WHERE id = ANY(%s)",
                ([row[0] for row in project_rows],),
            )
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


def test_sync_project_identity_endpoint_reconciles_legacy_project_ids(client, monkeypatch, tmp_path: Path) -> None:
    """POST /api/projects/{id}/sync-identity should rename legacy project rows to the manifest id."""
    projects_root = tmp_path / "projects"
    repo_root = projects_root / "a-term"
    repo_root.mkdir(parents=True)
    (repo_root / "project.identity.json").write_text(
        json.dumps(
            {
                "project": {
                    "id": "a-term",
                    "repo_name": "a-term",
                    "legacy_ids": ["aterm", "terminal"],
                    "repo_aliases": ["aterm", "terminal"],
                    "display_name": "A-Term",
                }
            }
        )
    )

    from app import project_identity as project_identity_module

    project_identity_module._workspace_manifest_paths.cache_clear()
    project_identity_module._read_manifest.cache_clear()
    monkeypatch.setattr(project_identity_module, "_PROJECTS_ROOT", projects_root)

    reconcile_mock = AsyncMock()
    monkeypatch.setattr("app.api.projects.reconcile_agent_hub_project_identity", reconcile_mock)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (id, name, base_url, health_endpoint, root_path, category)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                "terminal",
                "Legacy A-Term",
                "http://localhost:8002",
                "/health",
                "/srv/workspaces/projects/legacy-a-term",
                "production",
            ),
        )
        cur.execute(
            """
            INSERT INTO backup_sources (id, name, path, source_type, project_id, enabled, retention_days)
            VALUES (%s, %s, %s, 'project', %s, %s, %s)
            """,
            (
                "terminal",
                "Legacy A-Term",
                "/srv/workspaces/projects/legacy-a-term",
                "terminal",
                True,
                30,
            ),
        )
        conn.commit()

    try:
        response = client.post("/api/projects/a-term/sync-identity")

        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == "a-term"
        assert payload["name"] == "A-Term"
        assert payload["root_path"] == str(repo_root)
        reconcile_mock.assert_awaited_once_with(
            requested_project_id="a-term",
            canonical_project_id="a-term",
            aliases=("a-term", "aterm", "terminal"),
            root_path=str(repo_root),
        )

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, name, root_path FROM projects WHERE id = 'a-term'")
            project_row = cur.fetchone()
            cur.execute("SELECT id FROM projects WHERE id = 'terminal'")
            legacy_project_row = cur.fetchone()
            cur.execute("SELECT id, name, path, project_id FROM backup_sources WHERE id = 'a-term'")
            backup_row = cur.fetchone()
            cur.execute("SELECT id FROM backup_sources WHERE id = 'terminal'")
            legacy_backup_row = cur.fetchone()

        assert project_row == ("a-term", "A-Term", str(repo_root))
        assert legacy_project_row is None
        assert backup_row == ("a-term", "A-Term", str(repo_root), "a-term")
        assert legacy_backup_row is None
    finally:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM backup_sources WHERE id = ANY(%s)", (["terminal", "aterm", "a-term"],))
            cur.execute("DELETE FROM projects WHERE id = ANY(%s)", (["terminal", "aterm", "a-term"],))
            conn.commit()
        project_identity_module._workspace_manifest_paths.cache_clear()
        project_identity_module._read_manifest.cache_clear()
