"""Tests for the projects CLI command group."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands._projects_helpers import detect_current_project
from cli.commands.projects import app

runner = CliRunner()


def test_projects_root_prints_canonical_root_path() -> None:
    with patch(
        "cli.commands._projects_helpers.projects_api",
        return_value={
            "id": "terminal",
            "name": "Terminal",
            "root_path": "/srv/workspaces/projects/terminal",
        },
    ):
        result = runner.invoke(app, ["root", "terminal"])

    assert result.exit_code == 0
    assert result.output.strip() == "/srv/workspaces/projects/terminal"


def test_projects_root_requires_root_path() -> None:
    with patch(
        "cli.commands._projects_helpers.projects_api",
        return_value={
            "id": "terminal",
            "name": "Terminal",
            "root_path": None,
        },
    ):
        result = runner.invoke(app, ["root", "terminal"])

    assert result.exit_code == 1
    assert "has no root_path configured" in result.output


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
                "https://test2.summitflow.dev",
                "--root-path",
                "/srv/workspaces/projects/test2",
                "--permission-tier",
                "yolo",
                "--auto-exec",
            ],
        )

    assert result.exit_code == 0
    mock_projects_api.assert_called_once_with(
        "POST",
        json={
            "id": "test2",
            "name": "Testbed",
            "base_url": "https://test2.summitflow.dev",
            "health_endpoint": "/health",
            "root_path": "/srv/workspaces/projects/test2",
            "agent_hub_permission": {
                "permission_tier": "yolo",
                "auto_exec_enabled": True,
            },
        },
    )


def test_detect_current_project_returns_none_when_cwd_deleted() -> None:
    with patch("cli.commands._projects_helpers.Path.cwd", side_effect=FileNotFoundError("deleted")):
        result = detect_current_project()

    assert result is None


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
            "base_url": "https://test3.summitflow.dev",
            "health_endpoint": "/health",
            "root_path": "/srv/workspaces/projects/test3",
        },
    )
