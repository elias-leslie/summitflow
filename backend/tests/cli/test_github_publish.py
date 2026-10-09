"""Required checks stay tied to current commit, with missing evidence pending."""
import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from cli.lib.github_publish import GitHub, GitHubError, check_state


def test_missing_required_check_is_pending():
    assert check_state([], [{'context': 'backend'}]) == 'pending'


def test_required_app_identity_must_match():
    checks = [{'name': 'backend', 'state': 'success', 'app_id': 2}]
    assert check_state(checks, [{'context': 'backend', 'integration_id': 3}]) == 'pending'


def test_failed_check_is_not_hidden_by_success():
    assert check_state([{'name': 'backend', 'state': 'failed'}, {'name': 'frontend', 'state': 'success'}], [{'context': 'backend'}]) == 'failed'


def test_rule_discovery_preserves_required_names(monkeypatch):
    client = GitHub(Path('/repo'), 'owner/repo')
    api = Mock(side_effect=[{'default_branch': 'main', 'allow_merge_commit': True}, [{'type': 'required_status_checks', 'parameters': {'required_status_checks': [{'context': 'backend'}]}}], None])
    monkeypatch.setattr(client, 'api', api)
    plan = client.plan()
    assert plan['requires_pr'] is True
    assert plan['required'] == [{'context': 'backend'}]
    assert api.call_args_list[1].args[0] == 'rules/branches/main?per_page=100'


def test_verified_archived_repository_is_actionable_before_other_api_calls(monkeypatch):
    client = GitHub(Path('/repo'), 'owner/repo')
    api = Mock(return_value={'archived': True})
    monkeypatch.setattr(client, 'api', api)
    with pytest.raises(GitHubError) as exc:
        client.plan()
    assert not exc.value.unavailable
    assert exc.value.reason == 'remote_repository_archived'
    assert api.call_args.args == ('',) and api.call_count == 1


def test_pr_head_change_blocks_merge(monkeypatch):
    client = GitHub(Path('/repo'), 'owner/repo')
    api = Mock(return_value={'head': {'sha': 'b'*40}, 'merged': False})
    monkeypatch.setattr(client, 'api', api)
    with pytest.raises(GitHubError, match='head changed'):
        client.finish_pr(7, 'a'*40, {'required': [], 'merge_method': 'merge', 'base': 'main'})
    assert api.call_count == 1


def test_no_workflows_and_no_checks_is_not_applicable(monkeypatch):
    client = GitHub(Path('/repo'), 'owner/repo')
    monkeypatch.setattr(client, 'pages', Mock(return_value=[]))
    monkeypatch.setattr(client, 'api', Mock(return_value={'tree': []}))
    assert client.observe('a'*40, [])['state'] == 'not_applicable'


def test_registered_ci_without_runs_remains_pending(monkeypatch):
    client = GitHub(Path('/repo'), 'owner/repo')
    monkeypatch.setattr(client, 'pages', Mock(side_effect=[[], [], [], [{'state': 'active', 'path': 'dynamic/github-code-scanning/codeql'}]]))
    monkeypatch.setattr(client, 'api', Mock(return_value={'tree': []}))
    result = client.observe('a'*40, [])
    assert result['state'] == 'success' and result['optional_state'] == 'pending'


def test_merged_pr_resume_observes_merge_sha(monkeypatch):
    client = GitHub(Path('/repo'), 'owner/repo')
    api = Mock(return_value={'head': {'sha': 'a'*40}, 'merged': True, 'merge_commit_sha': 'b'*40})
    monkeypatch.setattr(client, 'api', api)
    observe = Mock(return_value={'state': 'pending', 'sha': 'b'*40})
    monkeypatch.setattr(client, 'observe', observe)
    result = client.finish_pr(7, 'a'*40, {'required': [], 'merge_method': 'merge', 'base': 'main'})
    assert result['merge_sha'] == 'b'*40
    assert observe.call_args_list[0].args == ('b'*40, [])
    assert observe.call_args_list[1].kwargs['event'] == 'pull_request'
    assert api.call_count == 1


def test_merge_request_is_guarded_by_exact_head_sha(monkeypatch):
    client = GitHub(Path('/repo'), 'owner/repo')
    api = Mock(side_effect=[{'head': {'sha': 'a'*40}, 'merged': False}, {'merged': True, 'sha': 'b'*40}])
    monkeypatch.setattr(client, 'api', api)
    monkeypatch.setattr(client, 'observe', Mock(side_effect=[{'state': 'success'}, {'state': 'pending', 'sha': 'b'*40}]))
    result = client.finish_pr(7, 'a'*40, {'required': [], 'merge_method': 'merge', 'base': 'main'})
    assert result['state'] == 'pending'
    assert api.call_args.kwargs == {'method': 'PUT', 'body': {'sha': 'a'*40, 'merge_method': 'merge'}}


def test_closed_merged_pr_is_reused(monkeypatch):
    client = GitHub(Path('/repo'), 'owner/repo')
    pull = {'number': 7, 'state': 'closed', 'merged_at': 'date', 'head': {'sha': 'a'*40}}
    api = Mock(return_value=[pull])
    monkeypatch.setattr(client, 'api', api)
    assert client.pull_request('st/task-1', 'main', 'resume', 'a'*40) == pull
    assert api.call_count == 1


def test_same_source_pull_request_lookup_is_branch_independent(monkeypatch):
    client = GitHub(Path('/repo'), 'owner/repo')
    pulls = [
        {
            'number': 9,
            'state': 'open',
            'head': {'sha': 'a' * 40, 'ref': 'st/task-old'},
            'base': {'ref': 'main'},
        },
        {
            'number': 10,
            'state': 'open',
            'head': {'sha': 'b' * 40, 'ref': 'st/task-other'},
            'base': {'ref': 'main'},
        },
    ]
    monkeypatch.setattr(client, 'pages', Mock(return_value=pulls))

    assert client.source_pull_request('main', 'a' * 40) == pulls[0]


def test_unpublished_exact_source_pr_lookup_is_absent_not_a_provider_failure(monkeypatch):
    from cli.lib import github_publish

    sha = 'a' * 40
    response = subprocess.CompletedProcess([], 1, 'HTTP/2.0 422 Unprocessable Entity\r\n\r\n' +
        json.dumps({'message': f'No commit found for SHA: {sha}'}), 'untrusted stderr')
    request = Mock(return_value=response)
    monkeypatch.setattr(github_publish.subprocess, 'run', request)
    client = GitHub(Path('/repo'), 'owner/repo')
    assert client.source_pull_request('main', sha) is None
    assert request.call_args.args[0][2] == f'repos/owner/repo/commits/{sha}/pulls?per_page=100&page=1'
    assert '--include' in request.call_args.args[0]
    assert request.call_args.args[0][request.call_args.args[0].index('--method') + 1] == 'GET'


@pytest.mark.parametrize(('status', 'message', 'sha'), [
    (401, f'No commit found for SHA: {"a" * 40}', 'a' * 40),
    (403, 'Resource not accessible by integration', 'a' * 40),
    (404, 'Not Found', 'a' * 40),
    (429, 'Rate limit exceeded', 'a' * 40),
    (422, 'Validation Failed', 'a' * 40),
    (422, f'No commit found for SHA: {"b" * 40}', 'a' * 40),
    (422, f'No commit found for SHA: {"a" * 40}; try another route', 'a' * 40),
    (422, 'No commit found for SHA: main', 'main'),
])
def test_source_pr_lookup_does_not_suppress_auth_rate_or_other_absence(monkeypatch, status, message, sha):
    from cli.lib import github_publish

    response = subprocess.CompletedProcess([], 1, f'HTTP/2.0 {status} Response\r\n\r\n' +
        json.dumps({'message': message}), f'No commit found for SHA: {"a" * 40}')
    monkeypatch.setattr(github_publish.subprocess, 'run', Mock(return_value=response))
    with pytest.raises(GitHubError) as exc:
        GitHub(Path('/repo'), 'owner/repo').source_pull_request('main', sha)
    assert exc.value.status_code == status and exc.value.response_message == message


def test_absence_after_partial_pr_pages_does_not_erase_prior_evidence(monkeypatch):
    from cli.lib import github_publish

    sha = 'a' * 40
    responses = [
        subprocess.CompletedProcess([], 0, 'HTTP/2.0 200 OK\r\n\r\n' + json.dumps([{}] * 100), ''),
        subprocess.CompletedProcess([], 1, 'HTTP/2.0 422 Unprocessable Entity\r\n\r\n' +
            json.dumps({'message': f'No commit found for SHA: {sha}'}), ''),
    ]
    request = Mock(side_effect=responses)
    monkeypatch.setattr(github_publish.subprocess, 'run', request)
    with pytest.raises(GitHubError):
        GitHub(Path('/repo'), 'owner/repo').source_pull_request('main', sha)
    assert request.call_count == 2


def test_dependency_update_creation_is_separate_from_commit_validation(monkeypatch):
    client = GitHub(Path('/repo'), 'owner/repo')
    workflow = {'path': 'dynamic/dependabot/dependabot-updates', 'check_suite_id': 9, 'name': 'Update dependency', 'conclusion': 'failure'}
    checks = [{'name': 'Dependabot', 'status': 'completed', 'conclusion': 'failure', 'check_suite': {'id': 9}},
              {'name': 'backend', 'status': 'completed', 'conclusion': 'success', 'check_suite': {'id': 10}}]
    monkeypatch.setattr(client, 'pages', Mock(side_effect=[[workflow], checks, [], []]))
    monkeypatch.setattr(client, 'api', Mock(return_value={'tree': []}))
    result = client.observe('a'*40, [{'context': 'backend'}])
    assert result['state'] == 'success'
    assert result['unrelated_workflows'][0]['conclusion'] == 'failure'


def test_explicit_required_dependency_job_cannot_be_excluded(monkeypatch):
    client = GitHub(Path('/repo'), 'owner/repo')
    workflow = {'path': 'dynamic/dependabot/dependabot-updates', 'check_suite_id': 9, 'name': 'Update dependency'}
    checks = [{'name': 'Dependabot', 'status': 'completed', 'conclusion': 'failure', 'check_suite': {'id': 9}}]
    monkeypatch.setattr(client, 'pages', Mock(side_effect=[[workflow], checks, []]))
    assert client.observe('a'*40, [{'context': 'Dependabot'}])['state'] == 'failed'


@pytest.mark.parametrize('suffix', ['', '.'])
def test_private_free_plan_has_no_enforceable_protection(monkeypatch, suffix):
    client = GitHub(Path('/repo'), 'owner/repo')
    unavailable = GitHubError('Private protection unsupported', status_code=403,
                              response_message='Upgrade to GitHub Pro or make this repository public to enable this feature' + suffix)
    monkeypatch.setattr(client, 'api', Mock(side_effect=[{'private': True, 'default_branch': 'main'}, unavailable, unavailable]))
    assert client.plan()['requires_pr'] is False


def test_general_private_auth_failure_stays_blocked(monkeypatch):
    client = GitHub(Path('/repo'), 'owner/repo')
    monkeypatch.setattr(client, 'api', Mock(side_effect=[{'private': True, 'default_branch': 'main'}, GitHubError('Resource not accessible (HTTP 403)')]))
    with pytest.raises(GitHubError, match='Resource not accessible'):
        client.plan()


def test_manual_only_workflow_does_not_create_permanent_pending(monkeypatch):
    import base64
    client = GitHub(Path('/repo'), 'owner/repo')
    monkeypatch.setattr(client, 'pages', Mock(side_effect=[[], [], [], [{'state': 'active', 'path': '.github/workflows/manual.yml'}]]))
    monkeypatch.setattr(client, 'api', Mock(side_effect=[{'tree': [{'path': '.github/workflows/manual.yml', 'type': 'blob'}]}, {'encoding': 'base64', 'content': base64.b64encode(b'on: workflow_dispatch\njobs: {}').decode()}]))
    assert client.observe('a'*40, [])['state'] == 'not_applicable'


def test_dependency_update_workflow_alone_is_not_commit_ci(monkeypatch):
    client = GitHub(Path('/repo'), 'owner/repo')
    monkeypatch.setattr(client, 'pages', Mock(side_effect=[[], [], [], [{'state': 'active', 'path': 'dynamic/dependabot/dependabot-updates'}]]))
    monkeypatch.setattr(client, 'api', Mock(return_value={'tree': []}))
    assert client.observe('a'*40, [])['state'] == 'not_applicable'


def test_new_workflow_before_actions_index_updates_remains_pending(monkeypatch):
    import base64
    client = GitHub(Path('/repo'), 'owner/repo')
    monkeypatch.setattr(client, 'pages', Mock(return_value=[]))
    api = Mock(side_effect=[
        {'tree': [{'path': '.github/workflows/ci.yml', 'type': 'blob'}]},
        {'content': base64.b64encode(b'on: [push]\njobs: {}').decode()},
    ])
    monkeypatch.setattr(client, 'api', api)
    result = client.observe('a'*40, [], branch='main')
    assert result['state'] == 'success' and result['optional_state'] == 'pending'
    assert api.call_args_list[0].args == (f"git/trees/{'a'*40}?recursive=1",)


def test_truncated_tree_cannot_prove_ci_absent(monkeypatch):
    client = GitHub(Path('/repo'), 'owner/repo')
    monkeypatch.setattr(client, 'pages', Mock(return_value=[]))
    monkeypatch.setattr(client, 'api', Mock(return_value={'tree': [], 'truncated': True}))
    with pytest.raises(GitHubError, match='truncated'):
        client.observe('a'*40, [])


@pytest.mark.parametrize('existing_required', [False, True])
def test_successful_check_does_not_hide_workflow_still_waiting_to_start(monkeypatch, existing_required):
    import base64
    client = GitHub(Path('/repo'), 'owner/repo')
    early = {'name': 'early', 'status': 'completed', 'conclusion': 'success'}
    monkeypatch.setattr(client, 'pages', Mock(side_effect=[[], [early], [], []]))
    monkeypatch.setattr(client, 'api', Mock(side_effect=[
        {'tree': [{'path': '.github/workflows/slow.yml', 'type': 'blob'}]},
        {'content': base64.b64encode(b'on: [push]\njobs: {}').decode()},
    ]))
    required = [{'context': 'early'}] if existing_required else []
    result = client.observe('a'*40, required, branch='main')
    assert result['state'] == 'success' and result['optional_state'] == 'pending'


def test_deleted_workflow_index_entry_cannot_block_no_ci_commit(monkeypatch):
    client = GitHub(Path('/repo'), 'owner/repo')
    monkeypatch.setattr(client, 'pages', Mock(side_effect=[[], [], [], [
        {'state': 'active', 'path': '.github/workflows/deleted.yml'}]]))
    monkeypatch.setattr(client, 'api', Mock(return_value={'tree': []}))
    assert client.observe('a'*40, [], branch='main')['state'] == 'not_applicable'


@pytest.mark.parametrize(('filters', 'branch', 'expected'), [
    ('tags: ["v*"]', 'main', False),
    ('branches: [main]', 'other', False),
    ('branches-ignore: ["release/*"]', 'release/deep/name', True),
    ('branches: ["release/v[0-9]+"]', 'release/v12', True),
])
def test_workflow_branch_filters_do_not_guess_github_globs(monkeypatch, filters, branch, expected):
    import base64
    client = GitHub(Path('/repo'), 'owner/repo')
    document = f'on:\n  push:\n    {filters}\njobs: {{}}'
    monkeypatch.setattr(client, 'api', Mock(return_value={'content': base64.b64encode(document.encode()).decode()}))
    assert client.workflow_applies({'state': 'active', 'path': '.github/workflows/ci.yml'},
                                   'a'*40, event='push', branch=branch) is expected


@pytest.mark.parametrize(('push_state', 'pr_state', 'expected'), [
    ('failed', 'success', 'failed'), ('pending', 'success', 'pending'),
    ('not_applicable', 'success', 'success'), ('not_applicable', 'not_applicable', 'not_applicable'),
])
def test_existing_pr_evidence_cannot_hide_push_failure(monkeypatch, push_state, pr_state, expected):
    client = GitHub(Path('/repo'), 'owner/repo')
    monkeypatch.setattr(client, 'observe', Mock(side_effect=[
        {'state': push_state, 'sha': 'a'*40, 'checks': []},
        {'state': pr_state, 'sha': 'a'*40, 'checks': []},
    ]))
    monkeypatch.setattr(client, 'pages', Mock(return_value=[{
        'number': 1, 'html_url': 'https://github.com/owner/repo/pull/1',
        'head': {'sha': 'a'*40}, 'base': {'ref': 'main'}}]))
    assert client.observe_feature_branch('a'*40, [], 'feature')['state'] == expected


@pytest.mark.parametrize(('paths', 'expected'), [
    (['deploy/backend.Dockerfile', 'deploy/ha/docker-compose.test.yml'], False),
    (['backend/app.py', 'docs/readme.md'], True),
    (None, True),
])
def test_mac_installer_push_filter_uses_exact_range(monkeypatch, paths, expected):
    import base64
    client = GitHub(Path('/repo'), 'owner/repo')
    document = 'on:\n  push:\n    branches: [main]\n    paths: ["backend/**", ".github/workflows/macos.yml"]\n'
    monkeypatch.setattr(client, 'api', Mock(return_value={'content': base64.b64encode(document.encode()).decode()}))
    assert client.workflow_applies({'state': 'active', 'path': '.github/workflows/macos.yml'},
                                   'a'*40, event='push', branch='main', changed_paths=paths) is expected


@pytest.mark.parametrize(('scope_sha', 'scope_branch', 'paths', 'expected'), [
    ('a'*40, 'main', ['deploy/backend.Dockerfile'], 'success'),
    ('a'*40, 'main', ['backend/app.py', 'docs.md'], 'pending'),
    ('b'*40, 'main', ['deploy/backend.Dockerfile'], 'pending'),
    ('a'*40, 'other', ['deploy/backend.Dockerfile'], 'pending'),
    ('a'*40, 'main', None, 'pending'),
])
def test_filtered_missing_workflow_uses_only_exact_push_evidence(monkeypatch, scope_sha, scope_branch, paths, expected):
    import base64
    client = GitHub(Path('/repo'), 'owner/repo')
    client.push_scope = {'sha': scope_sha, 'branch': scope_branch, 'paths': paths}
    monkeypatch.setattr(client, 'pages', Mock(side_effect=[[], [
        {'name': 'CI', 'status': 'completed', 'conclusion': 'success'}], [], []]))
    monkeypatch.setattr(client, 'api', Mock(side_effect=[
        {'tree': [{'path': '.github/workflows/mac.yml', 'type': 'blob'}]},
        {'content': base64.b64encode(b'on:\n  push:\n    paths: ["backend/**"]\n').decode()},
    ]))
    result = client.observe('a'*40, [], branch='main')
    assert result['state'] == 'success'
    assert result['optional_state'] == ('pending' if expected == 'pending' else 'success')


@pytest.mark.parametrize(('head', 'count', 'expected'), [('a'*40, 1, False), ('b'*40, 1, True), ('a'*40, 2, True)])
def test_pr_path_scope_requires_complete_current_head_files(monkeypatch, head, count, expected):
    import base64
    client = GitHub(Path('/repo'), 'owner/repo')
    client.pull_number = 7
    monkeypatch.setattr(client, 'pages', Mock(return_value=[{'filename': 'docs.md'}]))
    monkeypatch.setattr(client, 'api', Mock(side_effect=[
        {'content': base64.b64encode(b'on:\n  pull_request:\n    paths: ["backend/**"]\n').decode()},
        {'head': {'sha': head}, 'changed_files': count},
    ]))
    assert client.workflow_applies({'state': 'active', 'path': '.github/workflows/mac.yml'},
                                   'a'*40, event='pull_request', branch='main') is expected


@pytest.mark.parametrize("branches", [[], [{"name": "other"}]])
def test_missing_base_is_initial_only_when_remote_has_no_branches(monkeypatch, branches):
    client = GitHub(Path('/repo'), 'owner/repo')
    api = Mock(side_effect=[GitHubError('Branch not found', status_code=404, response_message='Branch not found'), branches])
    monkeypatch.setattr(client, 'api', api)
    if branches:
        with pytest.raises(GitHubError, match='Branch not found'):
            client.base_sha('main')
    else:
        assert client.base_sha('main') is None
    assert api.call_args.args == ('branches?per_page=1',)


def test_base_auth_error_is_not_an_empty_repository(monkeypatch):
    client = GitHub(Path('/repo'), 'owner/repo')
    api = Mock(side_effect=GitHubError('Not Found (HTTP 404)'))
    monkeypatch.setattr(client, 'api', api)
    with pytest.raises(GitHubError):
        client.base_sha('main')
    assert api.call_count == 1


@pytest.mark.parametrize('status,headers,unavailable,reason', [
    (401, '', True, 'remote_authentication_unavailable'),
    (403, '', True, 'remote_authentication_unavailable'),
    (403, 'X-RateLimit-Remaining: 0\r\n', True, 'remote_rate_limited'),
    (403, 'Retry-After: 60\r\n', True, 'remote_rate_limited'),
    (404, '', True, 'remote_api_unavailable'),
    (429, '', True, 'remote_rate_limited'),
    (503, '', True, 'remote_api_unavailable'),
    (422, '', False, 'remote_publication_failed'),
])
def test_api_outages_use_http_envelope_not_diagnostics(monkeypatch, status, headers, unavailable, reason):
    from cli.lib import github_publish
    output = f'HTTP/2.0 {status} Response\r\n{headers}\r\n{{"message":"fixture-private-diagnostic"}}'
    monkeypatch.setattr(github_publish.subprocess, 'run', Mock(return_value=subprocess.CompletedProcess([], 1, output, 'fixture-secret-token')))
    with pytest.raises(GitHubError) as exc:
        GitHub(Path('/repo'), 'owner/repo').api('')
    assert exc.value.unavailable is unavailable
    assert exc.value.reason == reason and exc.value.status_code == status
    assert 'fixture' not in str(exc.value)


@pytest.mark.parametrize('code,reason', [(1, 'remote_api_unavailable'), (4, 'remote_authentication_unavailable')])
def test_cli_failure_without_http_response_is_unknown_not_source_failure(monkeypatch, code, reason):
    from cli.lib import github_publish
    monkeypatch.setattr(github_publish.subprocess, 'run', Mock(return_value=subprocess.CompletedProcess([], code, '', 'do not interpret this diagnostic')))
    with pytest.raises(GitHubError) as exc:
        GitHub(Path('/repo'), 'owner/repo').api('')
    assert exc.value.unavailable and exc.value.reason == reason


def test_success_and_absent_protection_parse_included_headers(monkeypatch):
    from cli.lib import github_publish
    runner = Mock(side_effect=[subprocess.CompletedProcess([], 0, 'HTTP/2.0 200 OK\nX-Request: fixture\n\n{"default_branch":"main"}', ''),
                               subprocess.CompletedProcess([], 1, 'HTTP/2.0 404 Not Found\n\n{"message":"Branch not protected"}', '')])
    monkeypatch.setattr(github_publish.subprocess, 'run', runner)
    client = GitHub(Path('/repo'), 'owner/repo')
    assert client.api('') == {'default_branch': 'main'}
    assert client.api('branches/main/protection', absent_ok=True) is None
    assert '--include' in runner.call_args.args[0]


def test_optional_failure_does_not_hide_required_success():
    checks = [{"name": "required", "state": "success"}, {"name": "optional", "state": "failed"}]
    assert check_state(checks, [{"context": "required"}]) == "success"
    assert check_state(checks, []) == "success"


def test_optional_checks_remain_visible_when_requirements_pass(monkeypatch):
    client = GitHub(Path("/repo"), "owner/repo")
    responses = {"actions/runs?head_sha=" + "a" * 40: [],
        "commits/" + "a" * 40 + "/check-runs?filter=latest": [{"name": "extra", "status": "completed", "conclusion": "failure"}],
        "commits/" + "a" * 40 + "/statuses": [], "actions/workflows": []}
    monkeypatch.setattr(client, "pages", lambda path, *_: responses[path])
    monkeypatch.setattr(client, "api", lambda *_: {"tree": []})
    result = client.observe("a" * 40, [])
    assert result["state"] == "success"
    assert result["requirements_state"] == "known"
    assert result["optional_checks"] == [{"name": "extra", "state": "failed", "app_id": None, "url": None}]
