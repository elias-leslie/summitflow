"""Tests for the projects CLI command group."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands._projects_helpers import detect_current_project
from cli.commands.projects import app

runner = CliRunner()
PUBLIC_PROJECTS_ROOT = Path.home() / ".local" / "share" / "summitflow" / "workspaces" / "projects"


def test_projects_root_prints_canonical_root_path() -> None:
    with patch(
        "cli.commands._projects_helpers.projects_api",
        return_value={
            "id": "a-term",
            "name": "A-Term",
            "root_path": "/srv/workspaces/projects/a-term",
        },
    ):
        result = runner.invoke(app, ["root", "a-term"])

    assert result.exit_code == 0
    assert result.output.strip() == "/srv/workspaces/projects/a-term"


def test_projects_root_requires_root_path() -> None:
    with patch(
        "cli.commands._projects_helpers.projects_api",
        return_value={
            "id": "a-term",
            "name": "A-Term",
            "root_path": None,
        },
    ):
        result = runner.invoke(app, ["root", "a-term"])

    assert result.exit_code == 1
    assert "has no root_path configured" in result.output


def test_projects_sync_identity_hits_sync_endpoint() -> None:
    with patch(
        "cli.commands._projects_helpers.projects_api",
        return_value={
            "id": "a-term",
            "name": "A-Term",
            "root_path": "/srv/workspaces/projects/a-term",
        },
    ) as mock_projects_api:
        result = runner.invoke(app, ["sync-identity", "terminal"])

    assert result.exit_code == 0
    mock_projects_api.assert_called_once_with("POST", "/terminal/sync-identity")


def test_projects_create_sends_permission_bootstrap_fields() -> None:
    with patch(
        "cli.commands._projects_helpers.projects_api",
        return_value={"id": "test2", "name": "Testbed"},
    ) as mock_projects_api:
        result = runner.invoke(
            app,
            [
                "create",
                "test2",
                "Testbed",
                "--base-url",
                "https://test2.example.com",
                "--root-path",
                "/srv/workspaces/projects/test2",
                "--permission-tier",
                "full",
            ],
        )

    assert result.exit_code == 0
    mock_projects_api.assert_called_once_with(
        "POST",
        json={
            "id": "test2",
            "name": "Testbed",
            "base_url": "https://test2.example.com",
            "health_endpoint": "/health",
            "root_path": "/srv/workspaces/projects/test2",
            "agent_hub_permission": {
                "permission_tier": "full",
            },
        },
    )


def test_projects_create_rejects_legacy_auto_exec_option_without_creating_project() -> None:
    with patch("cli.commands._projects_helpers.projects_api") as mock_projects_api:
        result = runner.invoke(
            app,
            ["create", "test2", "Testbed", "--base-url", "https://test2.example.com", "--auto-exec"],
        )

    assert result.exit_code == 2
    assert "Agent Hub Automations" in result.output
    mock_projects_api.assert_not_called()


def test_projects_create_rejects_legacy_execution_window_option_without_creating_project() -> None:
    with patch("cli.commands._projects_helpers.projects_api") as mock_projects_api:
        result = runner.invoke(
            app,
            ["create", "test2", "Testbed", "--base-url", "https://test2.example.com", "--execution-start-hour", "8"],
        )

    assert result.exit_code == 2
    assert "Agent Hub Automations" in result.output
    mock_projects_api.assert_not_called()


def test_detect_current_project_returns_none_when_cwd_deleted() -> None:
    with patch("cli.commands._projects_helpers.Path.cwd", side_effect=FileNotFoundError("deleted")):
        result = detect_current_project()

    assert result is None


def test_projects_list_detects_current_project_without_second_api_call() -> None:
    with (
        patch(
            "cli.commands._projects_helpers.Path.cwd",
            return_value=Path("/srv/workspaces/projects/summitflow"),
        ),
        patch(
            "cli.commands._projects_helpers.projects_api",
            return_value=[
                {
                    "id": "summitflow",
                    "name": "SummitFlow",
                    "root_path": "/srv/workspaces/projects/summitflow",
                }
            ],
        ) as mock_projects_api,
    ):
        result = runner.invoke(app, ["list"])

    assert result.exit_code == 0
    mock_projects_api.assert_called_once_with("GET")
    assert '"current": true' in result.output


def test_projects_create_derives_hosted_defaults() -> None:
    with patch(
        "cli.commands._projects_helpers.projects_api",
        return_value={"id": "test3", "name": "Testbed 3"},
    ) as mock_projects_api:
        result = runner.invoke(
            app,
            [
                "create",
                "test3",
                "Testbed 3",
                "--summitflow-hosted",
            ],
        )

    assert result.exit_code == 0
    mock_projects_api.assert_called_once_with(
        "POST",
        json={
            "id": "test3",
            "name": "Testbed 3",
            "health_endpoint": "/health",
            "root_path": str(PUBLIC_PROJECTS_ROOT / "test3"),
            "summitflow_hosted": True,
            "onboarding": {
                "enable_backup_schedule": True,
                "backup_frequency": "daily",
                "backup_retention_days": 30,
                "queue_initial_backup": True,
            },
        },
    )


def test_projects_create_can_disable_hosted_onboarding() -> None:
    with patch(
        "cli.commands._projects_helpers.projects_api",
        return_value={"id": "test3", "name": "Testbed 3"},
    ) as mock_projects_api:
        result = runner.invoke(
            app,
            [
                "create",
                "test3",
                "Testbed 3",
                "--summitflow-hosted",
                "--no-onboard",
            ],
        )

    assert result.exit_code == 0
    mock_projects_api.assert_called_once_with(
        "POST",
        json={
            "id": "test3",
            "name": "Testbed 3",
            "health_endpoint": "/health",
            "root_path": str(PUBLIC_PROJECTS_ROOT / "test3"),
            "summitflow_hosted": True,
        },
    )


def test_projects_create_marks_hosted_alias_projects_without_baking_domains() -> None:
    with patch(
        "cli.commands._projects_helpers.projects_api",
        return_value={"id": "monkey-fight", "name": "Monkey Fight"},
    ) as mock_projects_api:
        result = runner.invoke(
            app,
            [
                "create",
                "monkey-fight",
                "Monkey Fight",
                "--summitflow-hosted",
            ],
        )

    assert result.exit_code == 0
    mock_projects_api.assert_called_once_with(
        "POST",
        json={
            "id": "monkey-fight",
            "name": "Monkey Fight",
            "health_endpoint": "/health",
            "root_path": str(PUBLIC_PROJECTS_ROOT / "monkey-fight"),
            "summitflow_hosted": True,
            "onboarding": {
                "enable_backup_schedule": True,
                "backup_frequency": "daily",
                "backup_retention_days": 30,
                "queue_initial_backup": True,
            },
        },
    )


def test_projects_onboard_queues_standard_payload() -> None:
    with patch(
        "cli.commands._projects_helpers.projects_api",
        return_value={"status": "queued", "project_id": "vantage"},
    ) as mock_projects_api:
        result = runner.invoke(app, ["onboard", "vantage", "--no-initial-backup"])

    assert result.exit_code == 0
    mock_projects_api.assert_called_once_with(
        "POST",
        "/vantage/onboard",
        json={
            "enable_backup_schedule": True,
            "backup_frequency": "daily",
            "backup_retention_days": 30,
            "queue_initial_backup": False,
        },
    )


def test_projects_create_native_without_base_url() -> None:
    with patch(
        "cli.commands._projects_helpers.projects_api",
        return_value={"id": "fydor", "name": "Fydor", "base_url": ""},
    ) as mock_projects_api:
        result = runner.invoke(app, ["create", "fydor", "Fydor", "--native", "-r", "/srv/workspaces/projects/fydor"])

    assert result.exit_code == 0
    assert "Created project 'fydor'" in result.output
    body = mock_projects_api.call_args.kwargs["json"]
    assert body["native"] is True
    assert body["base_url"] == ""
    assert body["root_path"] == "/srv/workspaces/projects/fydor"


def test_projects_audit_reports_complete_inventory_and_representation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(tmp_path))
    active = tmp_path / "aico"
    active.mkdir()
    (active / ".git").mkdir()
    (active / "project.identity.json").write_text(json.dumps({
        "project": {"id": "aico", "lifecycle": "retired"},
        "services": {"backend": "aico-shell.service"},
    }))
    fixture = tmp_path / "test1"
    fixture.mkdir()
    projects = [
        {"id": "aico", "name": "Aico", "root_path": str(active), "lifecycle": "active", "category": "dev"},
        {"id": "test1", "name": "Test", "root_path": str(fixture), "lifecycle": "active", "category": "testing"},
    ]
    def api(path: str, *, required: bool = False):
        return {
            "/projects?include_inactive=true": (projects, None),
            "/projects": (projects[:1], None),
            "/backup-sources": ([{"id": "aico", "project_id": "aico", "path": "/stale", "enabled": False, "source_type": "project"}], None),
            "/docker/status": ([{"service": "aico-shell", "state": "running", "health": "healthy"}], None),
        }[path]
    with patch("cli.commands._projects_audit._get_list", side_effect=api):
        result = runner.invoke(app, ["audit"])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)["projects"]
    assert [row["id"] for row in rows] == ["aico", "test1"]
    assert rows[0]["checkout"]["git"] is True
    assert rows[0]["lifecycle_conflict"] is True
    assert rows[0]["visibility"]["observed_default_listing"] is True
    assert rows[0]["backup"]["status"] == "path_mismatch"
    assert rows[0]["backup"]["sources"][0]["enabled"] is False
    assert rows[0]["runtime"]["services"][0]["state"] == "running"
    assert rows[1]["visibility"]["expected_default_listing_and_picker"] is False
    assert rows[1]["backup"]["expected_enabled"] is False
    assert rows[1]["backup"]["status"] == "not_configured"
    assert rows[1]["runtime"]["declaration"] == "unknown"


def test_projects_audit_marks_unavailable_evidence_unknown(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(tmp_path))
    projects = [{"id": "native", "root_path": str(tmp_path), "lifecycle": "active", "category": "dev"}]
    def api(path: str, *, required: bool = False):
        if path == "/projects?include_inactive=true":
            return projects, None
        return None, "unavailable"
    with patch("cli.commands._projects_audit._get_list", side_effect=api):
        result = runner.invoke(app, ["audit", "native"])
    assert result.exit_code == 0, result.output
    row = json.loads(result.output)["projects"][0]
    assert row["visibility"]["observed_default_listing"] is None
    assert row["backup"]["status"] == "unknown"
    assert row["runtime"]["declaration"] == "unknown"


def test_projects_audit_detects_registry_checkout_drift_and_optional_runtime(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(tmp_path))
    checkout = tmp_path / "projects" / "native"
    checkout.mkdir(parents=True)
    (checkout / ".git").mkdir()
    (checkout / "project.identity.json").write_text(json.dumps({
        "project": {"id": "native", "lifecycle": "active"},
        "services": {},
    }))
    stale = tmp_path / "old-release"
    projects = [{"id": "native", "root_path": str(stale), "lifecycle": "active", "category": "dev"}]
    def api(path: str, *, required: bool = False):
        return {
            "/projects?include_inactive=true": (projects, None),
            "/projects": (projects, None),
            "/backup-sources": ([], None),
            "/docker/status": ([], None),
        }[path]
    with patch("cli.commands._projects_audit._get_list", side_effect=api):
        result = runner.invoke(app, ["audit", "native"])
    assert result.exit_code == 0, result.output
    row = json.loads(result.output)["projects"][0]
    assert row["checkout"]["exists"] is False
    assert row["checkout"]["manifest_checkout"] == str(checkout)
    assert row["checkout"]["registry_matches_manifest_checkout"] is False
    assert row["runtime"]["declaration"] == "none"


def test_projects_audit_does_not_attribute_foreign_manifest(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(tmp_path))
    root = tmp_path / "aico"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "project.identity.json").write_text(json.dumps({
        "project": {"id": "other", "lifecycle": "retired"},
        "services": {"backend": "other.service"},
    }))
    projects = [{"id": "aico", "root_path": str(root), "lifecycle": "active", "category": "dev"}]
    def api(path: str, *, required: bool = False):
        return {
            "/projects?include_inactive=true": (projects, None),
            "/projects": (projects, None),
            "/backup-sources": ([], None),
            "/docker/status": ([{"service": "other", "state": "running"}], None),
        }[path]
    with patch("cli.commands._projects_audit._get_list", side_effect=api):
        result = runner.invoke(app, ["audit", "aico"])
    assert result.exit_code == 0, result.output
    row = json.loads(result.output)["projects"][0]
    assert row["checkout"]["manifest_project_id"] == "other"
    assert row["checkout"]["manifest_matches_project"] is False
    assert row["declared_lifecycle"] is None
    assert row["runtime"]["declaration"] == "unknown"


def test_projects_audit_ignores_foreign_conventional_checkout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ST_WORKSPACES_ROOT", str(tmp_path))
    candidate = tmp_path / "projects" / "aico"
    candidate.mkdir(parents=True)
    (candidate / "project.identity.json").write_text(json.dumps({
        "project": {"id": "other", "lifecycle": "retired"},
        "services": {"backend": "other.service"},
    }))
    projects = [{"id": "aico", "root_path": str(tmp_path / "missing"), "lifecycle": "active", "category": "dev"}]
    def api(path: str, *, required: bool = False):
        return {
            "/projects?include_inactive=true": (projects, None),
            "/projects": (projects, None),
            "/backup-sources": ([], None),
            "/docker/status": ([], None),
        }[path]
    with patch("cli.commands._projects_audit._get_list", side_effect=api):
        result = runner.invoke(app, ["audit", "aico"])
    assert result.exit_code == 0, result.output
    row = json.loads(result.output)["projects"][0]
    assert row["checkout"]["manifest_checkout"] is None
    assert row["declared_lifecycle"] is None
    assert row["runtime"]["declaration"] == "unknown"
