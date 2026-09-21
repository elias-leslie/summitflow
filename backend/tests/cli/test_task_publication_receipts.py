"""Optional publication retains source/checks independently of local closeout."""
from contextlib import nullcontext

import pytest

from app.storage import tasks
from cli.lib import commit_workflow

SHA = 'a' * 40


@pytest.fixture(autouse=True)
def mocked_commit_boundary(monkeypatch):
    # These tests cover DB receipt correlation, not Git mutation/lock behavior.
    monkeypatch.setattr(commit_workflow, 'repo_lock', lambda *args, **kwargs: nullcontext())


def _publish_work(repo, task_id, message):
    return commit_workflow.commit_repo(repo, message=message, task_id=task_id, push=True)


def test_explicit_publication_retains_published_source_and_ci(monkeypatch, tmp_path, test_project_id, cleanup_task, client):
    task = tasks.create_task(test_project_id, 'Publication receipt regression')
    cleanup_task(task['id'])
    monkeypatch.setattr('cli.lib.execution_context.resolve_checkout_project_id', lambda _repo: test_project_id)
    evidence = {
        'status': 'SUCCESS', 'sha': SHA, 'pushed': True,
        'publication_complete': True,
        'ci': {'state': 'success', 'sha': SHA, 'checks': [{'name': 'backend', 'conclusion': 'success'}]},
        'deployment': {'state': 'not_run'},
    }
    monkeypatch.setattr(commit_workflow, 'commit_git_revision', lambda *_args, **_kwargs: evidence)
    monkeypatch.setattr(commit_workflow, '_cleanup_after_publish', lambda _repo, result, **_kwargs: result)
    monkeypatch.setattr(commit_workflow, '_refresh_symbols_after_publish', lambda _repo, result: result)
    _publish_work(tmp_path, task['id'], 'Publish generic task')
    updated = tasks.get_task(task['id'])
    assert updated is not None
    assert updated['commits'] == [SHA]
    publication = updated['verification_result']['publication']
    assert publication['task_id'] == task['id']
    assert publication['source_commit'] == SHA
    assert publication['ci']['sha'] == SHA
    assert publication['ci']['state'] == 'success'
    assert 'deployment' not in publication
    route = f"/api/projects/{test_project_id}/tasks/{task['id']}"
    response = client.get(route)
    assert response.status_code == 200
    assert response.json()['verification_result']['publication'] == publication
    context = client.get(f"{route}/context?format=json")
    assert context.status_code == 200
    assert context.json()['task']['verification_result']['publication']['source_commit'] == SHA


def test_pending_then_clean_retry_persists_once_and_survives_completion(monkeypatch, tmp_path, test_project_id, cleanup_task):
    task = tasks.create_task(test_project_id, 'Pending publication receipt')
    cleanup_task(task['id'])
    tasks.update_task_status(task['id'], 'running')
    tasks.update_task(task['id'], verification_result={'independent_check': {'state': 'unknown'}})
    monkeypatch.setattr('cli.lib.execution_context.resolve_checkout_project_id', lambda _repo: test_project_id)
    evidence = {
        'status': 'PENDING', 'sha': SHA, 'pushed': True,
        'publication_complete': False,
        'ci': {'state': 'pending', 'sha': SHA, 'checks': []},
    }
    monkeypatch.setattr(commit_workflow, 'commit_git_revision', lambda *_args, **_kwargs: evidence)
    monkeypatch.setattr(commit_workflow, '_cleanup_after_publish', lambda _repo, result, **_kwargs: result)
    monkeypatch.setattr(commit_workflow, '_refresh_symbols_after_publish', lambda _repo, result: result)
    assert _publish_work(tmp_path, task['id'], 'Publish generic task')['status'] == 'PENDING'
    pending = tasks.get_task(task['id'])
    assert pending is not None
    assert pending['commits'] == [SHA]
    assert pending['verification_result']['publication']['publication_complete'] is False
    evidence.update(status='SUCCESS', pushed=False, publication_complete=True,
                    ci={'state': 'success', 'sha': SHA, 'checks': [{'name': 'backend', 'state': 'success'}]})
    _publish_work(tmp_path, task['id'], 'Publish generic task')
    _publish_work(tmp_path, task['id'], 'Publish generic task')
    from app.storage.tasks.closeout import store_verification
    store_verification(task['id'], test_project_id, {
        'acceptance': {'state': 'success', 'source_commit': SHA},
    })
    completed = tasks.update_task_status(task['id'], 'completed')
    assert completed is not None
    assert completed['commits'] == [SHA]
    proof = completed['verification_result']
    assert proof['independent_check'] == {'state': 'unknown'}
    assert proof['publication']['publication_complete'] is True
    assert proof['publication']['ci']['sha'] == SHA
    assert 'deployment' not in proof


def test_source_mismatch_and_project_mismatch_cannot_write_receipt(monkeypatch, tmp_path, test_project_id, cleanup_task):
    import pytest
    task = tasks.create_task(test_project_id, 'Receipt correlation failures')
    cleanup_task(task['id'])
    monkeypatch.setattr('cli.lib.execution_context.resolve_checkout_project_id', lambda _repo: test_project_id)
    evidence = {'status': 'SUCCESS', 'sha': SHA, 'publication_complete': True,
                'ci': {'state': 'success', 'sha': 'b' * 40, 'checks': []}}
    with pytest.raises(commit_workflow.CommitError, match='CI revision'):
        commit_workflow._record_task_publication(tmp_path, evidence, task_id=task['id'], push=True)
    evidence['ci']['sha'] = SHA
    monkeypatch.setattr('cli.lib.execution_context.resolve_checkout_project_id', lambda _repo: 'different-project')
    with pytest.raises(commit_workflow.CommitError, match='does not belong'):
        commit_workflow._record_task_publication(tmp_path, evidence, task_id=task['id'], push=True)
    unchanged = tasks.get_task(task['id'])
    assert unchanged is not None
    assert unchanged['commits'] == []
    assert unchanged['verification_result'] is None


def test_merge_receipt_uses_observed_merge_source(monkeypatch, tmp_path, test_project_id, cleanup_task):
    task = tasks.create_task(test_project_id, 'Merged source identity')
    cleanup_task(task['id'])
    monkeypatch.setattr('cli.lib.execution_context.resolve_checkout_project_id', lambda _repo: test_project_id)
    merge_sha = 'b' * 40
    evidence = {'status': 'SUCCESS', 'sha': SHA, 'merge_sha': merge_sha, 'publication_complete': True,
                'ci': {'state': 'success', 'sha': merge_sha, 'checks': []}}
    commit_workflow._record_task_publication(tmp_path, evidence, task_id=task['id'], push=True)
    stored = tasks.get_task(task['id'])
    assert stored is not None
    assert stored['commits'] == [merge_sha]
    assert stored['merge_sha'] == merge_sha
    assert stored['verification_result']['publication']['source_commit'] == merge_sha


def test_legacy_add_commit_remains_compatible_and_nonpublication_has_no_proof(test_project_id, cleanup_task):
    task = tasks.create_task(test_project_id, 'Legacy commit recording')
    cleanup_task(task['id'])
    tasks.add_commit(task['id'], SHA)
    stored = tasks.add_commit(task['id'], SHA)
    assert stored is not None
    assert stored['commits'] == [SHA]
    assert stored['verification_result'] is None


def test_new_commit_invalidates_but_preserves_prior_acceptance(test_project_id, cleanup_task):
    import pytest
    task = tasks.create_task(test_project_id, 'New work requires new acceptance')
    cleanup_task(task['id'])
    tasks.add_commit(task['id'], SHA)
    tasks.update_task(task['id'], verification_result={
        'acceptance': {'state': 'success', 'source_commit': SHA, 'acceptance_artifact': '/retained/receipt.json'},
        'deployment': {'state': 'succeeded', 'source_commit': SHA},
    })
    # Idempotent task linkage does not invalidate the already accepted source.
    same = tasks.add_commit(task['id'], SHA)
    assert same is not None
    assert same['verification_result']['acceptance']['state'] == 'success'
    stored = tasks.add_commit(task['id'], 'b' * 40)
    assert stored is not None
    assert stored['verification_result']['acceptance']['state'] == 'stale'
    assert stored['verification_result']['acceptance']['acceptance_artifact'] == '/retained/receipt.json'
    assert stored['verification_result']['deployment']['source_commit'] == SHA
    with pytest.raises(ValueError, match='acceptance remains incomplete'):
        tasks.update_task_status(task['id'], 'completed')


def test_pause_retains_durable_evidence_but_invalidates_completion_intent(test_project_id, cleanup_task):
    task = tasks.create_task(test_project_id, 'Pause preserves evidence')
    cleanup_task(task['id'])
    tasks.update_task_status(task['id'], 'running')
    tasks.update_task(task['id'], verification_result={
        'acceptance': {'state': 'success', 'source_commit': SHA, 'acceptance_artifact': '/retained/receipt.json'},
        'deployment': {'state': 'succeeded', 'source_commit': SHA},
        'closeout': {'state': 'pending', 'request_id': 'obsolete-request'},
    })
    stored = tasks.update_task_status(task['id'], 'paused')
    assert stored is not None
    proof = stored['verification_result']
    assert proof['acceptance']['state'] == 'stale'
    assert proof['acceptance']['acceptance_artifact'] == '/retained/receipt.json'
    assert proof['deployment']['source_commit'] == SHA
    assert 'closeout' not in proof


def test_receipt_persistence_failure_blocks_closeout(monkeypatch, tmp_path, test_project_id, cleanup_task):
    import pytest
    task = tasks.create_task(test_project_id, 'Receipt storage failure')
    cleanup_task(task['id'])
    monkeypatch.setattr('cli.lib.execution_context.resolve_checkout_project_id', lambda _repo: test_project_id)
    evidence = {'status': 'SUCCESS', 'sha': SHA, 'publication_complete': True,
                'ci': {'state': 'success', 'sha': SHA, 'checks': []}}
    monkeypatch.setattr(commit_workflow, 'commit_git_revision', lambda *_args, **_kwargs: evidence)

    def unavailable(*_args, **_kwargs):
        raise RuntimeError('storage unavailable')

    monkeypatch.setattr(tasks, 'add_commit', unavailable)
    with pytest.raises(commit_workflow.CommitError):
        _publish_work(tmp_path, task['id'], 'Publish task')
    unchanged = tasks.get_task(task['id'])
    assert unchanged is not None
    assert unchanged['status'] != 'completed'
    assert unchanged['commits'] == []


def test_unpublished_or_unbound_results_never_invent_check_success(monkeypatch, tmp_path):
    import pytest
    monkeypatch.setattr(tasks, 'add_commit', lambda *_args, **_kwargs: pytest.fail('must not record'))
    local = {'status': 'SUCCESS', 'sha': SHA}
    assert commit_workflow._record_task_publication(tmp_path, local, task_id='task-1', push=False) == local
    with pytest.raises(commit_workflow.CommitError, match='missing observed check evidence'):
        commit_workflow._record_task_publication(tmp_path, {**local, 'publication_complete': True}, task_id='task-1', push=True)
    with pytest.raises(commit_workflow.CommitError, match='successful check evidence'):
        commit_workflow._record_task_publication(tmp_path, {**local, 'publication_complete': True,
            'ci': {'state': 'failed', 'sha': SHA}}, task_id='task-1', push=True)



def test_jj_observer_receives_full_commit_identity(monkeypatch, tmp_path):
    import subprocess

    from cli.lib import jj_publish
    from cli.lib.jj_common import JJRevisionInfo
    monkeypatch.setattr(jj_publish, 'is_colocated', lambda _repo: True)
    monkeypatch.setattr(jj_publish, 'revision_info', lambda *_args: JJRevisionInfo('change', SHA[:12], False, False, 'Ready'))
    monkeypatch.setattr(jj_publish, 'run_jj', lambda *_args: subprocess.CompletedProcess([], 0, '', ''))
    monkeypatch.setattr(jj_publish, 'latest_operation_id', lambda _repo: 'operation')
    monkeypatch.setattr(jj_publish, 'run_git', lambda *_args: subprocess.CompletedProcess([], 0, SHA + '\n', ''))
    observed = []

    def publish(_repo, *, sha, **_kwargs):
        observed.append(sha)
        return {'sha': sha, 'publication_complete': True,
                'ci': {'state': 'success', 'sha': sha, 'checks': []}}

    monkeypatch.setattr(jj_publish, 'publish_git', publish)
    result = jj_publish.publish_current_revision(tmp_path, task_id='task-1', run_quality_gate=False)
    assert observed == [SHA]
    assert result['ci']['sha'] == SHA
