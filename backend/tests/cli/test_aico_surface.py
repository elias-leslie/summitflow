"""Tests for the Aico-supporting st surface: `st selection` and `st mandates`.

Selection is a Phase-1 stub (always empty); mandates is real and fetches the
mandate block from Agent Hub's progressive-context endpoint. Both follow the
frozen bare-payload output contract (docs/contracts/01-output-conventions.md).
"""

from __future__ import annotations

import json
from unittest.mock import patch

import typer
from typer.testing import CliRunner

from cli.commands import mandates as mandates_mod
from cli.commands.selection import app as selection_app
from cli.output_context import OutputContext

runner = CliRunner()

# Wrap the root-registered `mandates` leaf in a throwaway app so it can be
# driven through CliRunner with a real typer.Context (matching how main.py
# registers it via app.command("mandates")(...)).
_mandates_app = typer.Typer()
_mandates_app.command("mandates")(mandates_mod.mandates)


class TestSelection:
    def test_current_compact(self) -> None:
        result = runner.invoke(selection_app, ["current"])
        assert result.exit_code == 0
        assert "selection:kind=empty" in result.stdout

    def test_current_json_is_bare(self) -> None:
        result = runner.invoke(selection_app, ["current"], obj=OutputContext(compact=False))
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"kind": "empty"}

    def test_history_compact(self) -> None:
        result = runner.invoke(selection_app, ["history", "--n", "5"])
        assert result.exit_code == 0
        assert "selection-history[0]" in result.stdout

    def test_history_json_is_bare(self) -> None:
        result = runner.invoke(selection_app, ["history"], obj=OutputContext(compact=False))
        assert result.exit_code == 0
        assert json.loads(result.stdout) == {"items": []}


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
