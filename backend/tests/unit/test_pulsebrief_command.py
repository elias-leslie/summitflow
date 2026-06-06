from __future__ import annotations

import subprocess
from unittest.mock import patch

from typer.testing import CliRunner

from cli.commands import pulsebrief

runner = CliRunner()


def test_pulsebrief_context_invokes_pulse_db_script():
    calls = []

    def fake_run(args, text=None, capture_output=None, check=None, timeout=None):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout='{"recent_briefs": []}\n', stderr='')

    with patch("cli.commands.pulsebrief.subprocess.run", side_effect=fake_run):
        result = runner.invoke(pulsebrief.app, ["context", "--cadence", "daily", "--limit", "3"])

    assert result.exit_code == 0
    assert "PULSE_CONTEXT:daily" in result.output
    assert calls[0][-4:] == ["context", "--cadence", "daily", "--limit", "3"][-4:]


def test_pulsebrief_approve_updates_proposal_status():
    def fake_run(args, text=None, capture_output=None, check=None, timeout=None):
        assert args[-3:] == ["proposal-status", "PIP123", "approved"]
        return subprocess.CompletedProcess(args, 0, stdout='{"status":"approved","proposal_id":"PIP123"}\n', stderr='')

    with patch("cli.commands.pulsebrief.subprocess.run", side_effect=fake_run):
        result = runner.invoke(pulsebrief.app, ["proposal", "approve", "PIP123"])

    assert result.exit_code == 0
    assert "PROPOSAL:PIP123|status=approved" in result.output
