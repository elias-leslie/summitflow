"""Regression coverage for the retired Pulse Briefing surface."""

from typer.testing import CliRunner

from cli.main import app


def test_pulsebrief_is_absent_from_root_help() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0, result.output
    assert "pulsebrief" not in result.output
