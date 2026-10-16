"""Startup mandate wording for st check, st pulse and st service rebuild."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from cli.commands.tools import app as tools_app

runner = CliRunner()


def _spec(surface: str) -> dict:
    result = runner.invoke(tools_app, ["manifest", "--surface", surface, "--format", "json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["tools"][0]


def test_check_mandate_defers_routine_checks_to_commit() -> None:
    spec = _spec("st.check")
    assert spec["tier"] == "mandate"
    assert "st commit already runs the quick check" in spec["when"]
    assert "before committing" not in spec["when"]
    assert any("never raw pytest" in item for item in spec["precautions"])


def test_pulse_is_no_longer_a_mandate() -> None:
    spec = _spec("st.pulse")
    assert spec["tier"] == "reference"
    assert spec["cmd"] == "st pulse"
    assert "precautions" not in spec


def test_rebuild_needs_no_permission_ask() -> None:
    spec = _spec("st.service.rebuild")
    assert spec["tier"] == "mandate"
    assert any(item.startswith("no ask needed: deploys committed HEAD only") for item in spec["precautions"])


def test_startup_inject_leaves_pulse_out() -> None:
    for density in ("core", "adaptive"):
        result = runner.invoke(tools_app, ["manifest", "--format", "inject", "--density", density])
        assert result.exit_code == 0, result.output
        assert "- st pulse" not in result.output
