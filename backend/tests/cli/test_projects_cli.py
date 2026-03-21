"""Tests for the projects CLI command group."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

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
