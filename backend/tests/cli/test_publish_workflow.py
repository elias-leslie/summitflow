"""Publication must distinguish delivery, CI, and merge outcomes."""
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from cli.lib import publish_workflow as publish


def test_later_publication_to_disposable_remote_preserves_newer_local_work(tmp_path, monkeypatch):
    """Real Git round trip, with no GitHub client/account or external remote."""
    from cli.lib.commit_workflow import run_git

    repo = tmp_path / 'source'
    remote = tmp_path / 'remote.git'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', '--bare', str(remote)], check=True)

    def git(*args):
        result = run_git(repo, list(args))
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    git('init', '-q', '--initial-branch=main')
    git('config', 'user.name', 'Local Publication Test')
    git('config', 'user.email', 'local@example.invalid')
    git('remote', 'add', 'origin', str(remote))
    (repo / 'work.txt').write_text('accepted locally\n')
    git('add', 'work.txt')
    git('commit', '-qm', 'local work')
    accepted = git('rev-parse', 'HEAD')
    (repo / 'work.txt').write_text('newer committed work\n')
    git('commit', '-qam', 'later local work')
    newer = git('rev-parse', 'HEAD')
    (repo / 'unfinished.txt').write_text('another agent is working\n')
    assert subprocess.run(['git', '--git-dir', str(remote), 'show-ref'], capture_output=True).returncode == 1
    github = Mock(side_effect=AssertionError('GitHub must not be consulted'))
    monkeypatch.setattr(publish, 'GitHub', github)

    result = publish.publish_git(repo, sha=accepted, task_id='local-test', message='optional publication', run_git=run_git)

    assert result['publication_complete'] is True
    assert result['ci']['state'] == 'not_applicable'
    assert git('ls-remote', 'origin', 'refs/heads/main').split()[0] == accepted
    assert git('rev-parse', 'HEAD') == newer
    assert (repo / 'unfinished.txt').read_text() == 'another agent is working\n'
    github.assert_not_called()


def test_non_github_delivery_is_explicitly_not_applicable():
    git = Mock(return_value=Mock(returncode=0, stdout="", stderr=""))
    git.side_effect = [Mock(returncode=0, stdout="/tmp/remote.git\n"), Mock(returncode=0, stdout="main"), Mock(returncode=0, stdout="", stderr="")]
    result = publish.publish_git(Path('/repo'), sha='a'*40, task_id='', message='fix', run_git=git)
    assert result['pushed'] is True
    assert result['ci']['state'] == 'not_applicable'
    assert result['publication_complete'] is True


def test_github_failure_keeps_pushed_commit(monkeypatch):
    client = Mock()
    client.plan.return_value = {'base': 'main', 'requires_pr': False, 'required': [], 'merge_method': 'merge'}
    client.observe.return_value = {'state': 'failed', 'sha': 'a'*40, 'checks': [{'name': 'backend', 'state': 'failed'}]}
    monkeypatch.setattr(publish, 'GitHub', Mock(return_value=client))
    git = Mock(return_value=Mock(returncode=0, stdout='', stderr=''))
    git.side_effect = [Mock(returncode=0, stdout='git@github.com:owner/repo.git\n'), Mock(returncode=0, stdout='main'), Mock(returncode=0, stdout='', stderr='')]
    result = publish.publish_git(Path('/repo'), sha='a'*40, task_id='', message='fix', run_git=git)
    assert result['pushed'] is True
    client.observe.assert_called_once_with('a'*40, [], branch='main')
    assert result['status'] == 'BLOCKED'
    assert result['publication_complete'] is False


def test_protected_delivery_uses_remote_branch_without_checkout_switch(monkeypatch):
    client = Mock()
    plan = {'base': 'main', 'requires_pr': True, 'required': [{'context': 'backend'}], 'merge_method': 'merge'}
    client.plan.return_value = plan
    client.pull_request.return_value = {'number': 7, 'html_url': 'https://github.com/owner/repo/pull/7'}
    client.finish_pr.return_value = {'state': 'pending', 'sha': 'a'*40, 'checks': []}
    client.source_pull_request.return_value = None
    monkeypatch.setattr(publish, 'GitHub', Mock(return_value=client))
    git = Mock(return_value=Mock(returncode=0, stdout='', stderr=''))
    git.side_effect = [Mock(returncode=0, stdout='https://github.com/owner/repo.git\n'), Mock(returncode=0, stdout='', stderr='')]
    result = publish.publish_git(Path('/repo'), sha='a'*40, task_id='task-123', message='fix', run_git=git)
    assert git.call_args.args[1] == ['push', 'origin', 'a'*40 + ':refs/heads/st/task-123']
    assert result['status'] == 'PENDING'
    assert result['pr_url'].endswith('/7')
    assert result['publication_complete'] is False


def test_push_failure_never_claims_delivery(monkeypatch):
    monkeypatch.setattr(publish, 'GitHub', Mock())
    git = Mock(side_effect=[Mock(returncode=0, stdout='/tmp/remote.git'), Mock(returncode=0, stdout='main'), Mock(returncode=1, stdout='', stderr='hook rejected')])
    with pytest.raises(publish.PublishError, match='hook rejected'):
        publish.publish_git(Path('/repo'), sha='a'*40, task_id='', message='fix', run_git=git)


def test_existing_remote_sha_only_observes_ci(monkeypatch):
    client = Mock()
    client.plan.return_value = {'base': 'main', 'requires_pr': True, 'required': []}
    client.base_sha.return_value = 'a'*40
    client.observe.return_value = {'state': 'pending', 'sha': 'a'*40, 'checks': []}
    monkeypatch.setattr(publish, 'GitHub', Mock(return_value=client))
    git = Mock(return_value=Mock(returncode=0, stdout='git@github.com:owner/repo.git'))
    result = publish.publish_git(Path('/repo'), sha='a'*40, task_id='task-1', message='resume', run_git=git)
    assert result['status'] == 'PENDING'
    assert result['pushed'] is False
    assert git.call_count == 1
    client.pull_request.assert_not_called()


def test_reconcile_defers_diverged_history_without_renaming_or_switching():
    git = Mock(side_effect=[Mock(returncode=0, stdout='main'), Mock(returncode=0, stdout=''),
                           Mock(returncode=0), Mock(returncode=1), Mock(returncode=0, stdout='a'*40),
                           Mock(returncode=1), Mock(returncode=0), Mock(returncode=0, stderr='')])
    result = publish.reconcile(Path('/repo'), 'main', git)
    assert result == {'state': 'deferred', 'reason': 'diverged_history_preserved'}
    assert git.call_count == 4


def test_reconcile_preserves_dirty_work_without_blocking_remote_result():
    git = Mock(side_effect=[Mock(returncode=0, stdout='main'), Mock(returncode=0, stdout=' M user.txt')])
    assert publish.reconcile(Path('/repo'), 'main', git)['state'] == 'deferred'
    assert git.call_count == 2


def test_closed_scheduled_window_never_inspects_or_publishes():
    git = Mock(side_effect=AssertionError('No activity after night window'))
    with pytest.raises(publish.PublishError, match='window is closed'):
        publish.publish_git(Path('/repo'), sha='a'*40, task_id='nightly', message='nightly',
                            run_git=git, activity_allowed=lambda: False)
    git.assert_not_called()


def test_scheduled_window_closure_before_push_retains_source(monkeypatch):
    client = Mock()
    client.plan.return_value = {'base': 'main', 'requires_pr': True, 'required': [], 'merge_method': 'merge'}
    client.base_sha.return_value = 'b'*40
    client.source_pull_request.return_value = None
    monkeypatch.setattr(publish, 'GitHub', Mock(return_value=client))
    window = Mock(side_effect=[True, False])
    git = Mock(return_value=Mock(returncode=0, stdout='git@github.com:owner/repo.git'))
    with pytest.raises(publish.PublishError, match='window is closed'):
        publish.publish_git(Path('/repo'), sha='a'*40, task_id='nightly', message='nightly',
                            run_git=git, activity_allowed=window)
    assert git.call_count == 1
    client.pull_request.assert_not_called()


def test_github_reads_and_merge_requests_stop_after_window_closure(monkeypatch):
    from cli.lib import github_publish

    client = github_publish.GitHub(Path('/repo'), 'owner/repo')
    client.activity_allowed = lambda: False
    external = Mock(side_effect=AssertionError('No GitHub request after window'))
    monkeypatch.setattr(github_publish.subprocess, 'run', external)
    for method in ('GET', 'PUT', 'POST'):
        with pytest.raises(github_publish.GitHubError, match='window is closed'):
            client.api('pulls/7/merge', method=method)
    external.assert_not_called()


def test_clean_reconciliation_only_fast_forwards():
    git = Mock(side_effect=[Mock(returncode=0, stdout='main'), Mock(returncode=0, stdout=''),
                           Mock(returncode=0), Mock(returncode=0), Mock(returncode=0, stderr='')])
    result = publish.reconcile(Path('/repo'), 'main', git)
    assert result['state'] == 'success'
    assert git.call_args.args[1] == ['merge', '--ff-only', 'origin/main']


def test_rule_lookup_failure_never_pushes(monkeypatch):
    from cli.lib.github_publish import GitHubError
    client = Mock()
    client.plan.side_effect = GitHubError('authentication unavailable')
    monkeypatch.setattr(publish, 'GitHub', Mock(return_value=client))
    git = Mock(return_value=Mock(returncode=0, stdout='git@github.com:owner/repo.git'))
    with pytest.raises(publish.PublishError, match='authentication unavailable'):
        publish.publish_git(Path('/repo'), sha='a'*40, task_id='', message='fix', run_git=git)
    assert git.call_count == 1


def test_rule_lookup_preserves_typed_outage_without_push(monkeypatch):
    from cli.lib.github_publish import GitHubError
    client = Mock()
    client.plan.side_effect = GitHubError('Unavailable', unavailable=True, reason='remote_authentication_unavailable')
    monkeypatch.setattr(publish, 'GitHub', Mock(return_value=client))
    git = Mock(return_value=Mock(returncode=0, stdout='git@github.com:owner/repo.git'))
    with pytest.raises(publish.PublishError) as exc:
        publish.publish_git(Path('/repo'), sha='a'*40, task_id='', message='fix', run_git=git)
    assert exc.value.unavailable and exc.value.reason == 'remote_authentication_unavailable'
    assert git.call_count == 1


@pytest.mark.parametrize('already_remote', [True, False])
@pytest.mark.parametrize('reason', ['remote_api_unavailable', 'outside_publication_window'])
def test_ci_provider_outage_retains_delivery_but_never_completes(monkeypatch, already_remote, reason):
    from cli.lib.github_publish import GitHubError
    client = Mock()
    client.plan.return_value = {'base': 'main', 'requires_pr': False, 'required': []}
    client.base_sha.return_value = 'a'*40 if already_remote else 'b'*40
    client.observe.side_effect = GitHubError('Unavailable', unavailable=True, reason=reason)
    monkeypatch.setattr(publish, 'GitHub', Mock(return_value=client))
    git = Mock(return_value=Mock(returncode=0, stdout='git@github.com:owner/repo.git', stderr=''))
    result = publish.publish_git(Path('/repo'), sha='a'*40, task_id='', message='fix', run_git=git, destination='main')
    assert result['status'] == 'PENDING' and not result['publication_complete']
    assert result['pushed'] is (not already_remote)
    assert result['reason'] == reason and result['ci']['sha'] == 'a'*40


@pytest.mark.parametrize('pr_head', ['a'*40, 'b'*40])
def test_existing_feature_pr_waits_for_its_exact_sha_ci_without_merging(monkeypatch, pr_head):
    from cli.lib.github_publish import GitHub

    client = GitHub(Path('/repo'), 'owner/repo')
    monkeypatch.setattr(client, 'plan', Mock(return_value={'base': 'main', 'requires_pr': False, 'required': []}))
    monkeypatch.setattr(client, 'base_sha', Mock(return_value='c'*40))
    observe = Mock(side_effect=[{'state': 'not_applicable', 'sha': 'a'*40, 'checks': []},
                                {'state': 'pending', 'sha': 'a'*40, 'checks': []}])
    monkeypatch.setattr(client, 'observe', observe)
    pages = Mock(return_value=[{'number': 1, 'html_url': 'https://github.com/owner/repo/pull/1',
                               'head': {'sha': pr_head}, 'base': {'ref': 'main'}}])
    monkeypatch.setattr(client, 'pages', pages)
    api = Mock(side_effect=AssertionError('must not create or merge a pull request'))
    monkeypatch.setattr(client, 'api', api)
    monkeypatch.setattr(publish, 'GitHub', Mock(return_value=client))
    git = Mock(side_effect=[Mock(returncode=0, stdout='git@github.com:owner/repo.git'),
                           Mock(returncode=0, stdout='feature/existing'), Mock(returncode=0)])
    result = publish.publish_git(Path('/repo'), sha='a'*40, task_id='', message='fix', run_git=git)
    assert result['status'] == 'PENDING'
    assert result['publication_complete'] is False
    assert result['pr_url'].endswith('/1')
    pages.assert_called_once()
    assert 'feature%2Fexisting' in pages.call_args.args[0]
    if pr_head == 'a'*40:
        assert observe.call_args.kwargs == {'event': 'pull_request', 'branch': 'main'}
    else:
        assert observe.call_count == 1  # Older PR metadata cannot supply current revision evidence.
    api.assert_not_called()



def test_empty_remote_publishes_initial_commit_with_ci_observation(monkeypatch):
    client = Mock()
    client.plan.return_value = {'base': 'main', 'requires_pr': False, 'required': []}
    client.base_sha.return_value = None
    client.observe.return_value = {'state': 'pending', 'sha': 'a'*40, 'checks': []}
    monkeypatch.setattr(publish, 'GitHub', Mock(return_value=client))
    git = Mock(side_effect=[Mock(returncode=0, stdout='git@github.com:owner/repo.git'),
                           Mock(returncode=0, stdout='main'), Mock(returncode=0, stdout='')])
    result = publish.publish_git(Path('/repo'), sha='a'*40, task_id='task-new', message='initial', run_git=git)
    assert git.call_args.args[1] == ['push', '--porcelain', 'origin', 'a'*40 + ':refs/heads/main']
    assert result['status'] == 'PENDING'
    client.observe.assert_called_once_with('a'*40, [], branch='main')


def test_isolated_empty_remote_uses_verified_explicit_default_without_branch_switch(monkeypatch):
    client = Mock()
    client.plan.return_value = {'base': 'main', 'requires_pr': False, 'required': []}
    client.base_sha.return_value = None
    client.observe.return_value = {'state': 'pending', 'sha': 'a'*40, 'checks': []}
    monkeypatch.setattr(publish, 'GitHub', Mock(return_value=client))
    git = Mock(side_effect=[Mock(returncode=0, stdout='git@github.com:owner/repo.git'),
                           Mock(returncode=0, stdout='', stderr='')])
    result = publish.publish_git(Path('/isolated'), sha='a'*40, task_id='nightly', message='initial',
                                 run_git=git, destination='main', reconcile_checkout=False)
    assert git.call_args.args[1] == ['push', '--porcelain', 'origin', 'a'*40 + ':refs/heads/main']
    assert git.call_count == 2 and result['status'] == 'PENDING'


def test_configured_destination_must_match_verified_remote_default_before_bootstrap(monkeypatch):
    client = Mock()
    client.plan.return_value = {'base': 'master', 'requires_pr': False, 'required': []}
    monkeypatch.setattr(publish, 'GitHub', Mock(return_value=client))
    git = Mock(return_value=Mock(returncode=0, stdout='git@github.com:owner/repo.git'))
    with pytest.raises(publish.PublishError, match='does not match the remote default'):
        publish.publish_git(Path('/isolated'), sha='a'*40, task_id='nightly', message='initial',
                            run_git=git, destination='main', reconcile_checkout=False)
    assert git.call_count == 1
    client.base_sha.assert_not_called()


def test_resume_direct_commit_after_main_advances_only_observes_original_ci(monkeypatch):
    client = Mock()
    client.plan.return_value = {'base': 'main', 'requires_pr': False, 'required': []}
    client.base_sha.return_value = 'b' * 40
    client.api.return_value = {'status': 'ahead'}
    client.observe.return_value = {'state': 'success', 'sha': 'a' * 40, 'checks': []}
    monkeypatch.setattr(publish, 'GitHub', Mock(return_value=client))
    git = Mock(return_value=Mock(returncode=0, stdout='git@github.com:owner/repo.git'))
    result = publish.publish_git(Path('/repo'), sha='a' * 40, task_id='task-1', message='done', run_git=git, resume=True)
    assert result['publication_complete'] is True
    assert result['pushed'] is False
    assert git.call_count == 1
    client.observe.assert_called_once_with('a' * 40, [], branch='main')


def test_resume_pr_does_not_recreate_remote_branch(monkeypatch):
    client = Mock()
    client.plan.return_value = {'base': 'main', 'requires_pr': True, 'required': []}
    client.base_sha.return_value = 'b' * 40
    client.pull_request.return_value = {'number': 7, 'html_url': 'https://github.com/owner/repo/pull/7'}
    client.finish_pr.return_value = {'state': 'success', 'sha': 'a' * 40, 'checks': []}
    client.source_pull_request.return_value = None
    monkeypatch.setattr(publish, 'GitHub', Mock(return_value=client))
    git = Mock(return_value=Mock(returncode=0, stdout='git@github.com:owner/repo.git'))
    result = publish.publish_git(Path('/repo'), sha='a' * 40, task_id='task-1', message='done', run_git=git, resume=True)
    assert result['publication_complete'] is True
    assert result['pushed'] is False
    assert git.call_count == 1


def test_protected_publication_reuses_same_source_pr_on_different_task_branch(monkeypatch):
    client = Mock()
    client.plan.return_value = {
        'base': 'main', 'requires_pr': True, 'required': [], 'merge_method': 'squash'
    }
    client.base_sha.return_value = 'b' * 40
    existing = {
        'number': 9,
        'html_url': 'https://github.com/owner/repo/pull/9',
        'head': {'sha': 'a' * 40, 'ref': 'st/task-old'},
        'base': {'ref': 'main'},
        'state': 'open',
    }
    client.source_pull_request.return_value = existing
    client.finish_pr.return_value = {'state': 'pending', 'sha': 'a' * 40, 'checks': []}
    monkeypatch.setattr(publish, 'GitHub', Mock(return_value=client))
    git = Mock(return_value=Mock(returncode=0, stdout='git@github.com:owner/repo.git', stderr=''))

    result = publish.publish_git(
        Path('/repo'), sha='a' * 40, task_id='task-new', message='resume', run_git=git
    )

    assert result['pushed'] is False
    assert result['pr_url'].endswith('/9')
    assert result['publish_branch'] == 'st/task-old'
    assert git.call_count == 1
    client.pull_request.assert_not_called()
    client.finish_pr.assert_called_once_with(9, 'a' * 40, client.plan.return_value)
