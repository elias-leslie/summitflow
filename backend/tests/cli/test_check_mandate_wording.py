"""st.check startup mandate wording (plan rank 2: st commit is the routine quality gate)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from cli.commands.tools import app as tools_app

runner = CliRunner()


def test_check_mandate_points_routine_verification_at_commit() -> None:
    result = runner.invoke(tools_app, ["manifest", "--surface", "st.check", "--format", "json"])
    assert result.exit_code == 0, result.output
    spec = json.loads(result.output)["tools"][0]
    assert spec["tier"] == "mandate"
    assert spec["when"] == "iterate on a failing check; st commit already runs the quick check"
    assert any("never raw pytest" in item for item in spec["precautions"])
