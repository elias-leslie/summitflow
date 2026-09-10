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


def test_native_start_requires_identity_and_preserves_mode(monkeypatch):
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None: calls.append((path, body)))
    runner = CliRunner()
    assert runner.invoke(neri.app, ['start', '--external']).exit_code != 0
    assert not calls
    result = runner.invoke(neri.app, ['start', '--external', '--controller-id', 'codex-a', '--verification'])
    assert result.exit_code == 0
    assert calls[0][1]['controller_mode'] == 'external'
    assert calls[0][1]['origin'] == 'verification'


def test_submit_preserves_idempotency_and_fencing_payload(monkeypatch, tmp_path):
    import json
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None: calls.append((path, body)))
    payload = {'kind': 'request', 'title': 'Inspect identity', 'purpose': 'Establish account', 'path': '/api/me'}
    file = tmp_path / 'proposal.json'
    file.write_text(json.dumps(payload))
    run_id = '11111111-1111-4111-8111-111111111111'
    command_id = '22222222-2222-4222-8222-222222222222'
    args = ['submit', run_id, '--file', str(file), '--command-id', command_id,
            '--controller-id', 'codex-a', '--revision', '3']
    runner = CliRunner()
    assert runner.invoke(neri.app, args).exit_code == 0
    assert runner.invoke(neri.app, args).exit_code == 0
    assert calls[0] == calls[1]
    assert calls[0] == (f'/api/runs/{run_id}/commands', {
        'command_id': command_id, 'controller_id': 'codex-a', 'controller_revision': 3,
        'kind': 'action', 'payload': payload,
    })


def test_context_and_assignment_are_not_execution(monkeypatch):
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None: calls.append((path, body)))
    runner = CliRunner()
    run_id = '11111111-1111-4111-8111-111111111111'
    assert runner.invoke(neri.app, ['context', run_id, '--role', 'reviewer']).exit_code == 0
    assert calls == [(f'/api/runs/{run_id}/context?role=reviewer', None)]
    assert runner.invoke(neri.app, ['assignment', run_id, '--file', '-'], input='[]').exit_code != 0
    assert len(calls) == 1
    assert runner.invoke(neri.app, ['assignment', run_id, '--file', '-'], input='{"role":"hunter"}').exit_code == 0
    assert calls[-1][0].endswith('/assignments')
