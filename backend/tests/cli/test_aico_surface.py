"""Tests for the Aico-supporting st surface: `st projects switch` and `st projects active`.

Tether reads the active-project pointer these commands persist and reports it
to Aico as the active project; both print bare JSON payloads.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands import projects as projects_mod
from cli.commands.projects import app as projects_app

runner = CliRunner()

class TestProjectsActive:
    def test_switch_validates_slug_and_persists_pointer(self, tmp_path) -> None:
        state_file = tmp_path / "active-project.json"
        with (
            patch.object(projects_mod, "_active_project_path", return_value=state_file),
            patch.object(
                projects_mod,
                "projects_api",
                return_value={"root_path": "/srv/workspaces/projects/aico"},
            ) as api,
        ):
            result = runner.invoke(projects_app, ["switch", "aico"])
        assert result.exit_code == 0
        api.assert_called_once_with("GET", "/aico")
        assert json.loads(result.stdout) == {
            "project_id": "aico",
            "project_root": "/srv/workspaces/projects/aico",
        }
        assert json.loads(state_file.read_text())["project_id"] == "aico"

    def test_active_returns_persisted_pointer(self, tmp_path) -> None:
        state_file = tmp_path / "active-project.json"
        state_file.write_text(json.dumps({"project_id": "aico", "project_root": "/x"}))
        with patch.object(projects_mod, "_active_project_path", return_value=state_file):
            result = runner.invoke(projects_app, ["active"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"project_id": "aico", "project_root": "/x"}

    def test_active_returns_null_when_unset(self, tmp_path) -> None:
        with patch.object(
            projects_mod, "_active_project_path", return_value=tmp_path / "none.json"
        ):
            result = runner.invoke(projects_app, ["active"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"project_id": None, "project_root": None}
