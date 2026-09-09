"""Required checks stay tied to current commit, with missing evidence pending."""
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
    assert check_state([{'name': 'backend', 'state': 'failed'}, {'name': 'frontend', 'state': 'success'}], []) == 'failed'


def test_rule_discovery_preserves_required_names(monkeypatch):
    client = GitHub(Path('/repo'), 'owner/repo')
    api = Mock(side_effect=[{'default_branch': 'main', 'allow_merge_commit': True}, [{'type': 'required_status_checks', 'parameters': {'required_status_checks': [{'context': 'backend'}]}}], None])
    monkeypatch.setattr(client, 'api', api)
    plan = client.plan()
    assert plan['requires_pr'] is True
    assert plan['required'] == [{'context': 'backend'}]
    assert api.call_args_list[1].args[0] == 'rules/branches/main?per_page=100'


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
    assert client.observe('a'*40, [])['state'] == 'pending'


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


def test_private_free_plan_has_no_enforceable_protection(monkeypatch):
    client = GitHub(Path('/repo'), 'owner/repo')
    unavailable = GitHubError('Upgrade to GitHub Pro or make this repository public to enable this feature (HTTP 403)')
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
    assert client.observe('a'*40, [], branch='main')['state'] == 'pending'
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
    assert client.observe('a'*40, required, branch='main')['state'] == 'pending'


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
    assert client.observe('a'*40, [], branch='main')['state'] == expected


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
    api = Mock(side_effect=[GitHubError('GitHub GET branches/main: gh: Branch not found (HTTP 404)'), branches])
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
