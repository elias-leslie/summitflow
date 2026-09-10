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


def test_native_background_selection_and_conflicting_modes(monkeypatch):
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None: calls.append((path, body)))
    runner = CliRunner()
    assert runner.invoke(neri.app, ['start', '--native', '--external']).exit_code != 0
    assert runner.invoke(neri.app, ['start', '--native', '--controller-id', 'interactive']).exit_code != 0
    assert not calls
    assert runner.invoke(neri.app, ['start', '--native']).exit_code == 0
    assert calls == [('/api/runs', {'variant': 'benchmark', 'guidance': 'helper', 'controller_mode': 'native'})]
    run_id = '11111111-1111-4111-8111-111111111111'
    assert runner.invoke(neri.app, ['controller', run_id, 'native', '--revision', '4']).exit_code == 0
    assert calls[-1][1] == {'mode': 'native', 'controller_id': None, 'expected_revision': 4}


def test_budget_reads_revision_and_updates_once(monkeypatch):
    calls = []

    def request(path, body=None, **kwargs):
        calls.append((path, body, kwargs))
        return {'revision': 7}

    monkeypatch.setattr(neri, 'request', request)
    runner = CliRunner()
    for invalid in ('-1', '101', '1.5'):
        assert runner.invoke(neri.app, ['budget', 'set', invalid]).exit_code != 0
    assert not calls
    for percent in (0, 100):
        calls.clear()
        assert runner.invoke(neri.app, ['budget', 'set', str(percent)]).exit_code == 0
        assert calls == [('/api/budget', None, {'emit': False}),
                         ('/api/budget', {'weekly_allowance_percent': percent, 'expected_revision': 7}, {'method': 'PUT'})]


def test_budget_missing_revision_does_not_write(monkeypatch):
    calls = []

    def request(path, body=None, **kwargs):
        calls.append((path, body))
        return {'revision': True}

    monkeypatch.setattr(neri, 'request', request)
    assert CliRunner().invoke(neri.app, ['budget', 'set', '25']).exit_code != 0
    assert calls == [('/api/budget', None)]


def test_budget_conflict_is_reported_without_overwriting_or_retry(monkeypatch):
    from types import SimpleNamespace

    calls = []

    class Client:
        def __init__(self, _url):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def get(self, path):
            calls.append(('GET', path))
            return {'revision': 4}

        def put(self, path, *, json_body):
            calls.append(('PUT', path, json_body))
            raise neri.APIError(409, 'Budget changed; refresh and retry')

    monkeypatch.setattr(neri, 'ProjectApiClient', Client)
    monkeypatch.setattr(neri, 'resolve_api_url', lambda _: SimpleNamespace(url='http://localhost:8017'))
    result = CliRunner().invoke(neri.app, ['budget', 'set', '30'])
    assert result.exit_code == 1
    assert 'Budget changed' in result.output
    assert [call[0] for call in calls] == ['GET', 'PUT']


def test_hypothesis_payloads_preserve_attribution_and_revision(monkeypatch):
    import json
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None, **kwargs: calls.append((path, body, kwargs)))
    runner = CliRunner()
    run_id = '11111111-1111-4111-8111-111111111111'
    hypothesis_id = '22222222-2222-4222-8222-222222222222'
    payload = {'statement': 'Check an invariant', 'actor': 'agent', 'controller_id': 'codex',
               'controller_revision': 2, 'expected_revision': 3, 'evidence_ids': [hypothesis_id]}
    assert runner.invoke(neri.app, ['hypothesis', 'update', run_id, hypothesis_id, '--file', '-'],
                         input=json.dumps(payload)).exit_code == 0
    assert calls == [(f'/api/runs/{run_id}/hypotheses/{hypothesis_id}', payload, {'method': 'PUT'})]
    assert runner.invoke(neri.app, ['hypothesis', 'list', run_id, '--include-archived']).exit_code == 0
    assert calls[-1][0] == f'/api/runs/{run_id}/hypotheses?include_archived=true'
    assert runner.invoke(neri.app, ['hypothesis', 'create', run_id, '--file', '-'], input='[]').exit_code != 0
    assert len(calls) == 2


def test_runtime_status_and_immediate_stop_use_canonical_api(monkeypatch):
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None, **kwargs: calls.append((path, body, kwargs)))
    runner = CliRunner()
    assert runner.invoke(neri.app, ['runtime', 'show']).exit_code == 0
    assert calls == [('/api/runtime-control', None, {})]
    calls.clear()
    assert runner.invoke(neri.app, ['runtime', 'stop']).exit_code == 0
    assert calls == [('/api/runtime-control', {'stopped': True, 'expected_revision': 1}, {'method': 'PUT'})]


def test_runtime_release_requires_explicit_revision_without_resuming(monkeypatch):
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None, **kwargs: calls.append((path, body, kwargs)))
    runner = CliRunner()
    assert runner.invoke(neri.app, ['runtime', 'release']).exit_code != 0
    assert runner.invoke(neri.app, ['runtime', 'release', '--revision', '0']).exit_code != 0
    assert not calls
    assert runner.invoke(neri.app, ['runtime', 'release', '--revision', '12']).exit_code == 0
    assert calls == [('/api/runtime-control', {'stopped': False, 'expected_revision': 12}, {'method': 'PUT'})]


def test_advisory_budget_help_does_not_promise_enforcement():
    runner = CliRunner()
    result = runner.invoke(neri.app, ['budget', '--help'])
    assert result.exit_code == 0 and 'do not gate execution' in result.output
    result = runner.invoke(neri.app, ['budget', 'set', '--help'])
    assert result.exit_code == 0 and 'does not cap or pause execution' in result.output
