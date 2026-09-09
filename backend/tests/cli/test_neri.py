"""Neri CLI sends controls to the canonical API, never directly to the lab."""
from typer.testing import CliRunner

from cli.commands import neri


def test_read_only_show_uses_canonical_api(monkeypatch):
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None: calls.append((path, body)))
    result = CliRunner().invoke(neri.app, ['show', '11111111-1111-4111-8111-111111111111'])
    assert result.exit_code == 0
    assert calls == [('/api/runs/11111111-1111-4111-8111-111111111111', None)]


def test_control_validates_action_and_requires_direction(monkeypatch):
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None: calls.append((path, body)))
    runner = CliRunner()
    run_id = '11111111-1111-4111-8111-111111111111'
    assert runner.invoke(neri.app, ['control', run_id, 'direct']).exit_code != 0
    assert runner.invoke(neri.app, ['control', run_id, 'shell']).exit_code != 0
    assert not calls
    assert runner.invoke(neri.app, ['control', run_id, 'step']).exit_code == 0
    assert calls[0][1] == {'action': 'step', 'message': ''}


def test_advanced_mode_does_not_change_execution_destination(monkeypatch):
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None: calls.append((path, body)))
    result = CliRunner().invoke(neri.app, ['start', '--variant', 'secure', '--advanced'])
    assert result.exit_code == 0
    assert calls == [('/api/runs', {'variant': 'secure', 'guidance': 'advanced'})]
