"""Contract snapshot tests for the Aico `st` surface (Phase 1).

Freezes the output *shapes* of the commands Aico's widgets and hooks consume,
per docs/contracts/02-st-surface.md in the aico repo. These are deliberately
shape assertions, not behavior tests: they fail CI when a JSON key, compact
prefix, or tag convention drifts, so a downstream Aico consumer never breaks
silently. Network-bound commands are mocked at their I/O boundary; the persisted
active-project pointer is redirected to a tmp file so the real one is untouched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import typer
from typer.testing import CliRunner

from cli.commands.mandates import mandates
from cli.commands.note import note
from cli.commands.projects import app as projects_app
from cli.commands.selection import app as selection_app
from cli.output_context import OutputContext

runner = CliRunner()

# JSON modes resolve OutputContext.is_compact -> False; compact is the default.
_JSON = OutputContext(compact=False)


def _json(result) -> dict[str, Any]:
    import json

    return json.loads(result.output)


def _wrap(fn):
    """Register a root-level command function under a throwaway Typer app."""
    app = typer.Typer()
    app.command()(fn)
    return app


class TestSelectionContract:
    def test_current_json_shape(self) -> None:
        res = runner.invoke(selection_app, ["current"], obj=_JSON)
        assert res.exit_code == 0
        assert _json(res) == {"kind": "empty"}

    def test_current_compact_prefix(self) -> None:
        res = runner.invoke(selection_app, ["current"])
        assert res.exit_code == 0
        assert res.output.strip() == "selection:kind=empty"

    def test_history_json_shape(self) -> None:
        res = runner.invoke(selection_app, ["history"], obj=_JSON)
        assert res.exit_code == 0
        assert _json(res) == {"items": []}

    def test_history_compact_prefix(self) -> None:
        res = runner.invoke(selection_app, ["history"])
        assert res.exit_code == 0
        assert res.output.strip() == "selection-history[0]{kind,text,ts}:"


class TestMandatesContract:
    def test_json_shape_items_and_count(self) -> None:
        items = ["**Mandate A**: do x", "**Mandate B**: do y"]
        with patch(
            "cli.commands.mandates.agent_hub_request",
            return_value={"mandates": {"items": items}},
        ):
            res = runner.invoke(_wrap(mandates), [], obj=_JSON)
        assert res.exit_code == 0
        payload = _json(res)
        assert set(payload) == {"items", "count"}
        assert payload["items"] == items
        assert payload["count"] == len(items)

    def test_compact_prints_items_verbatim(self) -> None:
        items = ["**Mandate A**: do x", "**Mandate B**: do y"]
        with patch(
            "cli.commands.mandates.agent_hub_request",
            return_value={"mandates": {"items": items}},
        ):
            res = runner.invoke(_wrap(mandates), [])
        assert res.exit_code == 0
        assert res.output.strip().splitlines() == items


class TestProjectsSwitchContract:
    def test_json_shape(self, tmp_path: Path) -> None:
        pointer = tmp_path / "active-project.json"
        with (
            patch(
                "cli.commands.projects.projects_api",
                return_value={"root_path": "/srv/workspaces/projects/aico"},
            ),
            patch("cli.commands.projects._active_project_path", return_value=pointer),
        ):
            res = runner.invoke(projects_app, ["switch", "aico"], obj=_JSON)
        assert res.exit_code == 0
        assert _json(res) == {
            "project_id": "aico",
            "project_root": "/srv/workspaces/projects/aico",
            "switched": True,
        }


class TestNoteContract:
    def test_forces_kind_note_tag_and_note_content(self) -> None:
        with patch("cli.commands.note.save_impl", MagicMock()) as save:
            res = runner.invoke(_wrap(note), ["Check the deploy after merge"])
        assert res.exit_code == 0
        args = save.call_args.args
        content, tags = args[1], args[-3]
        assert content.startswith("**Note**: ")
        assert "Check the deploy after merge" in content
        assert tags == "#kind:note"

    def test_merges_extra_tags_after_kind_note(self) -> None:
        with patch("cli.commands.note.save_impl", MagicMock()) as save:
            res = runner.invoke(
                _wrap(note),
                ["note text", "--tags", "#widget:claude-code"],
            )
        assert res.exit_code == 0
        assert save.call_args.args[-3] == "#kind:note,#widget:claude-code"
