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
    assert result.exit_code == 0 and 'do not gate execution' in ' '.join(result.output.split())
    result = runner.invoke(neri.app, ['budget', 'set', '--help'])
    assert result.exit_code == 0 and 'does not cap or pause execution' in ' '.join(result.output.split())
def test_orchestrator_context_before_run_and_profiles(monkeypatch):
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None: calls.append((path, body)))
    runner = CliRunner()
    assert runner.invoke(neri.app, ['context', '--role', 'orchestrator']).exit_code == 0
    assert calls == [('/api/orchestration-context', None)]
    assert runner.invoke(neri.app, ['context']).exit_code != 0
    assert runner.invoke(neri.app, ['start', '--hunter-profile', 'sol-daybreak-blue']).exit_code != 0
    assert runner.invoke(neri.app, ['start', '--native', '--hunter-profile', 'sol-daybreak-blue', '--reviewer-profile', 'astra-standard']).exit_code == 0
    assert calls[-1][1]['reasoning_profiles'] == {'hunter': 'sol-daybreak-blue', 'reviewer': 'astra-standard'}
    assert runner.invoke(neri.app, ['start', '--native', '--hunter-profile', 'sol-automatic']).exit_code == 0
    assert calls[-1][1]['reasoning_profiles'] == {'hunter': 'sol-automatic', 'reviewer': 'astra-standard'}
    assert runner.invoke(neri.app, ['start', '--native', '--reviewer-profile', 'astra-standard']).exit_code == 0
    assert calls[-1][1]['reasoning_profiles'] == {'hunter': 'sol-automatic', 'reviewer': 'astra-standard'}



def test_workbench_uses_canonical_routes_and_preserves_operation_identity(monkeypatch, tmp_path):
    import json
    calls=[]
    monkeypatch.setattr(neri,'request',lambda path,body=None:calls.append((path,body)))
    run_id='11111111-1111-4111-8111-111111111111'
    operation_id='22222222-2222-4222-8222-222222222222'
    payload={'id':operation_id,'kind':'http','purpose':'Observe','path':'/','actor':'agent','controller_id':'terminal','controller_revision':1}
    file=tmp_path/'operation.json'
    file.write_text(json.dumps(payload))
    runner=CliRunner()
    assert runner.invoke(neri.app,['workbench','send',run_id,'--file',str(file)]).exit_code==0
    assert calls[-1]==(f'/api/workbench/{run_id}/operations',payload)
    assert runner.invoke(neri.app,['workbench','traffic',run_id]).exit_code==0
    assert calls[-1]==(f'/api/workbench/{run_id}/traffic',None)
    assert runner.invoke(neri.app,['workbench','operation',run_id,operation_id]).exit_code==0
    assert calls[-1]==(f'/api/workbench/{run_id}/operations/{operation_id}',None)


def test_workbench_reset_preserves_json_and_returns_receipt_or_error_without_retry(monkeypatch, tmp_path):
    import json

    import httpx

    calls = []
    status = 200
    receipt = {'id': '22222222-2222-4222-8222-222222222222', 'status': 'complete'}

    def handle(request):
        calls.append((request.method, request.url.path, json.loads(request.content)))
        body = receipt if status == 200 else {'detail': 'Inspect the retained reset receipt'}
        return httpx.Response(status, json=body)

    client = httpx.Client
    monkeypatch.setenv('ST_NERI_API_URL', 'https://neri.invalid')
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: client(transport=httpx.MockTransport(handle), **kwargs))
    run_id = '11111111-1111-4111-8111-111111111111'
    payload = {
        'id': receipt['id'],
        'expected_target_manifest_digest': 'a' * 64,
        'actor': 'agent',
        'controller_id': 'native-tui',
        'controller_revision': 3,
    }
    file = tmp_path / 'reset.json'
    file.write_text(json.dumps(payload))
    runner = CliRunner()
    for status in (200, 409, 500):
        for source in (str(file), '-'):
            calls.clear()
            result = runner.invoke(neri.app, ['workbench', 'reset', run_id, '--file', source],
                                   input=json.dumps(payload) if source == '-' else None)
            assert result.exit_code == (0 if status == 200 else 1), result.output
            if status == 200:
                assert json.loads(result.output) == receipt
            else:
                assert json.loads(result.output) == {
                    'ok': False, 'error': 'neri_api_error', 'detail': 'Inspect the retained reset receipt',
                }
            assert calls == [('POST', f'/api/workbench/{run_id}/target-reset', payload)]


def test_workbench_reset_rejects_invalid_input_before_transport(monkeypatch):
    calls = []
    monkeypatch.setattr(neri, 'request', lambda *args, **kwargs: calls.append((args, kwargs)))
    runner = CliRunner()
    args = ['workbench', 'reset', '11111111-1111-4111-8111-111111111111']
    assert runner.invoke(neri.app, args).exit_code != 0
    for invalid in ('[]', 'null', '{invalid'):
        assert runner.invoke(neri.app, [*args, '--file', '-'], input=invalid).exit_code != 0
    assert runner.invoke(neri.app, ['workbench', 'reset', 'bad-id', '--file', '-'], input='{}').exit_code != 0
    assert not calls


def test_workbench_reset_help_and_manifest_describe_admission_and_receipt_handling():
    import json

    from cli.commands.tools import app as tools_app

    runner = CliRunner()
    help_result = runner.invoke(neri.app, ['workbench', 'reset', '--help'])
    assert help_result.exit_code == 0
    help_text = ' '.join(help_result.output.split())
    for phrase in ('fixed target', 'global stop', 'paused/settled run', 'request identity', 'retained receipt', 'new ID'):
        assert phrase in help_text
    result = runner.invoke(tools_app, ['manifest', '--surface', 'st.neri.workbench.reset', '--format', 'json'])
    assert result.exit_code == 0
    specs = json.loads(result.output)['tools']
    assert len(specs) == 1
    assert specs[0]['cmd'] == 'st neri workbench reset <run-id> --file reset.json'
    precautions = ' '.join(specs[0]['precautions'])
    for phrase in ('global stop', 'paused/settled run', 'fixed target recreation', 'request identity', 'retained receipt', 'new ID'):
        assert phrase in precautions


def test_capabilities_preserves_legacy_and_describes_registry_entry(monkeypatch):
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None: calls.append((path, body)))
    runner = CliRunner()
    assert runner.invoke(neri.app, ['capabilities']).exit_code == 0
    assert runner.invoke(neri.app, ['capabilities', '--compact']).exit_code == 0
    assert runner.invoke(neri.app, ['capabilities', 'generic-capability']).exit_code == 0
    assert calls == [('/api/capabilities', None), ('/api/capabilities?compact=true', None),
                     ('/api/capabilities/generic-capability', None)]


def test_evolution_and_help_are_thin_clients(monkeypatch):
    import json
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None, **kwargs: calls.append((path, body, kwargs)))
    runner = CliRunner()
    identity = '11111111-1111-4111-8111-111111111111'
    routes = [
        (['evolution', 'list'], '/api/evolution-attempts'),
        (['evolution', 'list', '--run-id', identity], f'/api/evolution-attempts?run_id={identity}'),
        (['evolution', 'show', identity], f'/api/evolution-attempts/{identity}'),
        (['help', 'list', '--status', 'open'], '/api/help-requests?status=open'),
        (['help', 'show', identity], f'/api/help-requests/{identity}'),
        (['help', 'context', identity], f'/api/help-requests/{identity}/context'),
    ]
    for args, route in routes:
        assert runner.invoke(neri.app, args).exit_code == 0
        assert calls[-1] == (route, None, {})
    body = {'expected_revision': 3, 'summary': 'Assistance recorded'}
    for command, suffix, kwargs in [('attach', 'attachments', {}), ('resolve', 'resolution', {'method': 'PUT'})]:
        assert runner.invoke(neri.app, ['help', command, identity, '--file', '-'], input=json.dumps(body)).exit_code == 0
        assert calls[-1] == (f'/api/help-requests/{identity}/{suffix}', body, kwargs)
    count = len(calls)
    assert runner.invoke(neri.app, ['help', 'resolve', identity, '--file', '-'], input='[]').exit_code != 0
    assert len(calls) == count


def test_target_discovery_uses_compact_api_and_encoded_identity(monkeypatch):
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None: calls.append((path, body)))
    runner = CliRunner()
    assert runner.invoke(neri.app, ['target', 'list']).exit_code == 0
    assert runner.invoke(neri.app, ['target', 'show', 'local-documents-v1']).exit_code == 0
    assert runner.invoke(neri.app, ['target', 'show', 'docs?version=2']).exit_code == 0
    assert calls == [
        ('/api/targets?compact=true', None),
        ('/api/targets/local-documents-v1', None),
        ('/api/targets/docs%3Fversion%3D2', None),
    ]


def test_target_writes_preserve_manifest_and_status_fence(monkeypatch, tmp_path):
    import json
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None, **kwargs: calls.append((path, body, kwargs)))
    runner = CliRunner()
    manifest = {
        'target_id': 'local-documents-v1', 'version': '1',
        'artifact_identity': 'sha256:fixture', 'executor_key': 'local-analysis',
        'manifest': {'domain': 'documents', 'resource_refs': ['fixture:documents'],
                     'setup': {'notes': 'Keep literal `text` and $(values).'}},
    }
    file = tmp_path / 'target.json'
    file.write_text(json.dumps(manifest))
    assert runner.invoke(neri.app, ['target', 'register', '--file', str(file)]).exit_code == 0
    assert calls[-1] == ('/api/targets', manifest, {})
    for expected, status in [('active', 'inactive'), ('inactive', 'active')]:
        body = {'manifest_digest': 'sha256:observed', 'expected_status': expected,
                'status': status, 'reason': 'Owner requested a reversible status change'}
        result = runner.invoke(neri.app, ['target', 'status', 'local-documents-v1', '--file', '-'],
                               input=json.dumps(body))
        assert result.exit_code == 0
        assert calls[-1] == ('/api/targets/local-documents-v1/status', body, {'method': 'PUT'})
    count = len(calls)
    for args in [['target', 'register'], ['target', 'status', 'local-documents-v1']]:
        for invalid in ['[]', '{invalid']:
            assert runner.invoke(neri.app, [*args, '--file', '-'], input=invalid).exit_code != 0
    assert len(calls) == count


def test_target_status_uses_shared_client_without_retrying_conflicts(monkeypatch):
    from types import SimpleNamespace

    from cli._client_base import APIError

    calls = []

    class Client:
        def __init__(self, url):
            assert url == 'http://localhost:8017'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def put(self, path, *, json_body):
            calls.append((path, json_body))
            raise APIError(409, 'Target status changed')

    monkeypatch.setattr(neri, 'ProjectApiClient', Client)
    monkeypatch.setattr(neri, 'resolve_api_url', lambda _: SimpleNamespace(url='http://localhost:8017'))
    result = CliRunner().invoke(
        neri.app, ['target', 'status', 'local-documents-v1', '--file', '-'],
        input='{"manifest_digest":"observed","expected_status":"active","status":"inactive","reason":"Pause"}',
    )
    assert result.exit_code == 1
    assert 'Target status changed' in result.stdout
    assert len(calls) == 1


def test_start_preserves_registered_target_and_external_controller(monkeypatch):
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None: calls.append((path, body)))
    result = CliRunner().invoke(neri.app, [
        'start', '--target-id', 'local-documents-v1', '--external',
        '--controller-id', 'document-assistant', '--title', 'Check document inventory',
    ])
    assert result.exit_code == 0
    assert calls == [('/api/runs', {
        'variant': 'benchmark', 'guidance': 'helper', 'target_id': 'local-documents-v1',
        'controller_mode': 'external', 'controller_id': 'document-assistant',
        'title': 'Check document inventory',
    })]


def test_evolution_transitions_are_explicit_posts(monkeypatch):
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None, **kwargs: calls.append((path, body, kwargs)))
    runner = CliRunner()
    attempt_id = '11111111-1111-4111-8111-111111111111'
    for transition in ['reconcile', 'qualify']:
        assert runner.invoke(neri.app, ['evolution', transition, attempt_id]).exit_code == 0
        assert calls[-1] == (f'/api/evolution-attempts/{attempt_id}/{transition}', {}, {})
    assert len(calls) == 2
    for transition in ['reconcile', 'qualify']:
        assert runner.invoke(neri.app, ['evolution', transition, 'not-a-uuid']).exit_code != 0
    assert len(calls) == 2


def test_evolution_files_preserve_gap_revision_and_verifier_identity(monkeypatch, tmp_path):
    import json
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None, **kwargs: calls.append((path, body, kwargs)))
    runner = CliRunner()
    identity = '11111111-1111-4111-8111-111111111111'
    payloads = [
        ('start', f'/api/runs/{identity}/evolution-attempts', {
            'gap_id': '22222222-2222-4222-8222-222222222222', 'gap_revision': 4,
            'owning_project': 'neri', 'implementation_envelope': {'objective': 'Read documents'},
            'baseline': {'event_id': 'retained-observation'}, 'neri_task_ids': ['task-document-read'],
        }),
        ('activate', f'/api/evolution-attempts/{identity}/activate', {
            'acceptance_id': '33333333-3333-4333-8333-333333333333',
            'capability_id': 'documents.read', 'package_id': 'neri-documents', 'version': '2',
            'artifact_digest': 'a' * 64, 'permissions': {'effect_class': 'read_only'},
            'manifest': {'input_schema_digest': 'b' * 64, 'output_schema_digest': 'c' * 64},
        }),
    ]
    for command, route, body in payloads:
        file = tmp_path / f'{command}.json'
        file.write_text(json.dumps(body))
        assert runner.invoke(neri.app, ['evolution', command, identity, '--file', str(file)]).exit_code == 0
        assert calls[-1] == (route, body, {})
        assert runner.invoke(neri.app, ['evolution', command, identity, '--file', '-'],
                             input=json.dumps(body)).exit_code == 0
        assert calls[-1] == (route, body, {})
    count = len(calls)
    for command, _, _ in payloads:
        assert runner.invoke(neri.app, ['evolution', command, identity, '--file', '-'], input='[]').exit_code != 0
    assert len(calls) == count


def test_grants_and_rollout_preserve_revisioned_authority_inputs(monkeypatch):
    import json
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None, **kwargs: calls.append((path, body, kwargs)))
    runner = CliRunner()
    identity = '11111111-1111-4111-8111-111111111111'
    assert runner.invoke(neri.app, ['grant', 'list', identity]).exit_code == 0
    assert calls[-1] == (f'/api/runs/{identity}/grants', None, {})
    assert runner.invoke(neri.app, ['kernel', 'rollout', 'show']).exit_code == 0
    assert calls[-1] == ('/api/kernel-rollout', None, {})
    grant = {
        'expected_revision': 3, 'domain': 'documents', 'resource_scope': {'local_only': True},
        'capability_ids': ['documents.read'], 'effect_classes': ['read_only'],
        'development_projects': ['neri'], 'deployment_environments': ['local'],
        'publication_allowed': False, 'provider_policy': {'silent_fallback': False},
        'automation_policy': {'gap_task_creation': 'disabled', 'managed_execution': False},
    }
    rollout = {'expected_revision': 2, 'enabled': False, 'acceptance_refs': [], 'reason': 'Manual verification'}
    commands = [
        (['grant', 'issue', identity], f'/api/runs/{identity}/grants', grant, {}),
        (['kernel', 'rollout', 'set'], '/api/kernel-rollout', rollout, {'method': 'PUT'}),
    ]
    for args, route, body, kwargs in commands:
        assert runner.invoke(neri.app, [*args, '--file', '-'], input=json.dumps(body)).exit_code == 0
        assert calls[-1] == (route, body, kwargs)
    count = len(calls)
    for args, _, _, _ in commands:
        for invalid in ['[]', '{invalid']:
            assert runner.invoke(neri.app, [*args, '--file', '-'], input=invalid).exit_code != 0
    assert len(calls) == count


def test_legacy_grant_upgrade_is_one_explicit_post(monkeypatch):
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None: calls.append((path, body)))
    runner = CliRunner()
    identity = '11111111-1111-4111-8111-111111111111'
    assert runner.invoke(neri.app, ['grant', 'upgrade', identity]).exit_code == 0
    assert calls == [(f'/api/runs/{identity}/grants/upgrade', {})]
    assert runner.invoke(neri.app, ['grant', 'upgrade', 'not-a-uuid']).exit_code != 0
    assert len(calls) == 1


def test_evolution_verify_preserves_receipt_and_expected_revision(monkeypatch, tmp_path):
    import json
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None: calls.append((path, body)))
    runner = CliRunner()
    identity = '11111111-1111-4111-8111-111111111111'
    payload = {'expected_revision': 7, 'receipt_id': '22222222-2222-4222-8222-222222222222'}
    file = tmp_path / 'verification.json'
    file.write_text(json.dumps(payload))
    for source in [str(file), '-']:
        result = runner.invoke(neri.app, ['evolution', 'verify', identity, '--file', source],
                               input=json.dumps(payload) if source == '-' else None)
        assert result.exit_code == 0
        assert calls[-1] == (f'/api/evolution-attempts/{identity}/verify', payload)
    count = len(calls)
    for invalid in ['[]', '{invalid']:
        assert runner.invoke(neri.app, ['evolution', 'verify', identity, '--file', '-'], input=invalid).exit_code != 0
    assert runner.invoke(neri.app, ['evolution', 'verify', 'not-a-uuid', '--file', str(file)]).exit_code != 0
    assert len(calls) == count


def test_evolution_resume_requires_revision_payload_and_preserves_help_fingerprint(monkeypatch, tmp_path):
    import json
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None: calls.append((path, body)))
    runner = CliRunner()
    identity = '11111111-1111-4111-8111-111111111111'
    args = ['evolution', 'resume', identity]
    assert runner.invoke(neri.app, args).exit_code != 0
    assert not calls
    payloads = [{'expected_revision': 7},
                {'expected_revision': 9, 'help_dependency_fingerprint': 'a' * 64}]
    for payload in payloads:
        file = tmp_path / 'resume.json'
        file.write_text(json.dumps(payload))
        for source in [str(file), '-']:
            result = runner.invoke(neri.app, [*args, '--file', source],
                                   input=json.dumps(payload) if source == '-' else None)
            assert result.exit_code == 0
            assert calls[-1] == (f'/api/evolution-attempts/{identity}/resume', payload)
    count = len(calls)
    assert runner.invoke(neri.app, [*args, '--file', '-'], input='[]').exit_code != 0
    assert len(calls) == count


def test_technique_reads_use_canonical_routes_and_encode_filters(monkeypatch):
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None: calls.append((path, body)))
    runner = CliRunner()
    run_id = '11111111-1111-4111-8111-111111111111'
    routes = [
        (['list'], '/api/techniques'),
        (['list', '--compact'], '/api/techniques?compact=true'),
        (['show', 'document-review'], '/api/techniques/document-review'),
        (['show', 'document?review', '--version', 'v1+review'], '/api/techniques/document%3Freview?version=v1%2Breview'),
        (['metrics'], '/api/techniques/metrics'),
        (['metrics', '--technique-id', 'document&review'], '/api/techniques/metrics?technique_id=document%26review'),
        (['uses', run_id], f'/api/runs/{run_id}/techniques'),
        (['recommendations', run_id], f'/api/runs/{run_id}/techniques/recommendations'),
    ]
    for args, route in routes:
        assert runner.invoke(neri.app, ['technique', *args]).exit_code == 0
        assert calls[-1] == (route, None)
    assert len(calls) == len(routes)


def test_technique_writes_preserve_case_identity_authority_and_revision(monkeypatch, tmp_path):
    import json
    calls = []
    monkeypatch.setattr(neri, 'request', lambda path, body=None, **kwargs: calls.append((path, body, kwargs)))
    runner = CliRunner()
    run_id = '11111111-1111-4111-8111-111111111111'
    use_id = '22222222-2222-4222-8222-222222222222'
    attribution = {'actor': 'agent', 'controller_id': 'document-assistant', 'controller_revision': 6}
    cases = [
        (['recommend', run_id], f'/api/runs/{run_id}/techniques/recommendations', {}, {
            **attribution, 'id': use_id, 'request_key': 'recommendation:1',
            'objective': 'Review the document inventory', 'objective_tags': ['documents'],
            'applicability_signals': [{'id': 'document-source', 'status': 'declared'}],
        }),
        (['select', run_id], f'/api/runs/{run_id}/techniques', {}, {
            **attribution, 'id': use_id, 'request_key': 'selection:1',
            'technique_id': 'document-review', 'technique_version': '1.0',
            'case_id': 'documents:1', 'case_ref': {'kind': 'document', 'ref': 'artifact:inventory'},
            'objective': 'Assess retained document evidence', 'parameter_refs': {'source': ['artifact:inventory']},
            'selection_mode': 'prospective', 'attempt_no': 1,
        }),
        (['update', run_id, use_id], f'/api/runs/{run_id}/techniques/{use_id}', {'method': 'PUT'}, {
            **attribution, 'expected_revision': 3, 'status': 'blocked', 'candidate_outcome': 'blocked',
            'evidence_refs': ['33333333-3333-4333-8333-333333333333'],
            'uncertainty': 'Waiting for source evidence; preserve literal `text` and $(values).',
        }),
    ]
    for args, route, kwargs, payload in cases:
        file = tmp_path / f'{args[0]}.json'
        file.write_text(json.dumps(payload))
        for source in [str(file), '-']:
            result = runner.invoke(neri.app, ['technique', *args, '--file', source],
                                   input=json.dumps(payload) if source == '-' else None)
            assert result.exit_code == 0
            assert calls[-1] == (route, payload, kwargs)
    assert len(calls) == 6


def test_technique_writes_reject_missing_or_malformed_inputs_before_transport(monkeypatch):
    calls = []
    monkeypatch.setattr(neri, 'request', lambda *args, **kwargs: calls.append((args, kwargs)))
    runner = CliRunner()
    run_id = '11111111-1111-4111-8111-111111111111'
    use_id = '22222222-2222-4222-8222-222222222222'
    commands = [['recommend', run_id], ['select', run_id], ['update', run_id, use_id]]
    for args in commands:
        assert runner.invoke(neri.app, ['technique', *args]).exit_code != 0
        for invalid in ['[]', '{invalid']:
            assert runner.invoke(neri.app, ['technique', *args, '--file', '-'], input=invalid).exit_code != 0
    for args in [['recommend', 'bad-id'], ['select', 'bad-id'], ['update', run_id, 'bad-id']]:
        assert runner.invoke(neri.app, ['technique', *args, '--file', '-'], input='{}').exit_code != 0
    assert not calls
