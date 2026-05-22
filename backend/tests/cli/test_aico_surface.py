"""Tests for the Aico-supporting st surface: `st selection` and `st mandates`.

Selection reads Aico's sidecar selection bus over HTTP (Phase 2); mandates
fetches the mandate block from Agent Hub's progressive-context endpoint. Both
follow the frozen bare-payload output contract (docs/contracts/01-output-conventions.md).
"""

from __future__ import annotations

import json
from unittest.mock import patch

import typer
from typer.testing import CliRunner

from cli.commands import mandates as mandates_mod
from cli.commands import note as note_mod
from cli.commands import projects as projects_mod
from cli.commands import selection as selection_mod
from cli.commands.projects import app as projects_app
from cli.commands.selection import app as selection_app
from cli.output_context import OutputContext

runner = CliRunner()

# Wrap the root-registered leaf commands in throwaway apps so they can be driven
# through CliRunner with a real typer.Context (matching how main.py registers
# them via app.command("mandates")(...) / app.command("note")(...)).
_mandates_app = typer.Typer()
_mandates_app.command("mandates")(mandates_mod.mandates)
_note_app = typer.Typer()
_note_app.command("note")(note_mod.note)


_DOM = {
    "kind": "dom",
    "snippet": "the selected text",
    "captured_at": "2026-05-22T20:00:00.000Z",
    "widget": None,
    "project": None,
    "meta": {"url": "http://x", "title": "X"},
}


class TestSelection:
    """`st selection` reads Aico's bus over HTTP; tests stub `_sidecar_get`."""

    def test_current_empty_compact(self) -> None:
        with patch.object(selection_mod, "_sidecar_get", return_value={"kind": "empty"}):
            result = runner.invoke(selection_app, ["current"])
        assert result.exit_code == 0
        assert "selection:kind=empty" in result.stdout

    def test_current_empty_json_is_bare(self) -> None:
        # A sidecar that is down returns {} from _sidecar_get → still empty.
        with patch.object(selection_mod, "_sidecar_get", return_value={}):
            result = runner.invoke(selection_app, ["current"], obj=OutputContext(compact=False))
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"kind": "empty"}

    def test_current_dom_compact_shows_snippet(self) -> None:
        with patch.object(selection_mod, "_sidecar_get", return_value=_DOM):
            result = runner.invoke(selection_app, ["current"])
        assert result.exit_code == 0
        assert "kind=dom" in result.stdout
        assert "the selected text" in result.stdout

    def test_current_dom_json_is_bare_record(self) -> None:
        with patch.object(selection_mod, "_sidecar_get", return_value=_DOM):
            result = runner.invoke(selection_app, ["current"], obj=OutputContext(compact=False))
        assert result.exit_code == 0
        assert json.loads(result.stdout) == _DOM

    def test_history_empty_compact(self) -> None:
        with patch.object(selection_mod, "_sidecar_get", return_value={"items": [], "count": 0}):
            result = runner.invoke(selection_app, ["history", "--n", "5"])
        assert result.exit_code == 0
        assert "selection-history[0]" in result.stdout

    def test_history_json_has_items_and_count(self) -> None:
        payload = {"items": [_DOM], "count": 1}
        with patch.object(selection_mod, "_sidecar_get", return_value=payload):
            result = runner.invoke(selection_app, ["history"], obj=OutputContext(compact=False))
        assert result.exit_code == 0
        assert json.loads(result.stdout) == payload


class TestMandates:
    def test_compact_prints_rendered_union(self) -> None:
        fake = {"mandates": {"items": ["**A**: do x.", "**B**: do y."], "count": 2}}
        with patch.object(mandates_mod, "agent_hub_request", return_value=fake) as call:
            result = runner.invoke(_mandates_app, [], obj=OutputContext(compact=True))
        assert result.exit_code == 0
        assert "**A**: do x." in result.stdout
        assert "**B**: do y." in result.stdout
        # Mandate block is deterministic; query is a stable placeholder.
        _, kwargs = call.call_args
        assert kwargs["params"]["query"] == "mandates"

    def test_json_is_bare_items_count(self) -> None:
        fake = {"mandates": {"items": ["**A**: do x."]}}
        with patch.object(mandates_mod, "agent_hub_request", return_value=fake):
            result = runner.invoke(_mandates_app, [], obj=OutputContext(compact=False))
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"items": ["**A**: do x."], "count": 1}

    def test_handles_empty_mandate_block(self) -> None:
        with patch.object(mandates_mod, "agent_hub_request", return_value={}):
            result = runner.invoke(_mandates_app, [], obj=OutputContext(compact=False))
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"items": [], "count": 0}


class TestNote:
    def test_saves_as_formatted_note_episode(self) -> None:
        with patch.object(note_mod, "save_impl") as save:
            result = runner.invoke(_note_app, ["Check the deploy after merge"])
        assert result.exit_code == 0
        args = save.call_args.args
        content, summary, tier = args[1], args[2], args[3]
        tags = args[16]
        assert content == "**Note**: Check the deploy after merge."
        assert tier == "reference"
        assert 10 <= len(summary) <= 40
        assert tags == "#kind:note"

    def test_merges_extra_tags_after_kind_note(self) -> None:
        with patch.object(note_mod, "save_impl") as save:
            result = runner.invoke(
                _note_app, ["Check the deploy after merge", "--tags", "#widget:claude-code"]
            )
        assert result.exit_code == 0
        assert save.call_args.args[16] == "#kind:note,#widget:claude-code"


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
