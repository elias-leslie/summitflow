"""Stored historical publication evidence survives retired commit publication."""

import pytest

from app.storage import tasks
from cli.lib import commit_workflow

SHA = 'a' * 40


def test_historical_publication_retained_in_task_api_and_context(test_project_id, cleanup_task, client):
    task = tasks.create_task(test_project_id, 'Historical publication receipt')
    cleanup_task(task['id'])
    publication = {
        'task_id': task['id'], 'project_id': test_project_id,
        'source_commit': SHA, 'publication_complete': True,
        'ci': {'state': 'success', 'sha': SHA, 'checks': [{'name': 'backend', 'conclusion': 'success'}]},
    }
    stored = tasks.add_commit(task['id'], SHA, project_id=test_project_id, publication=publication)
    assert stored is not None
    assert stored['commits'] == [SHA]
    assert stored['verification_result']['publication'] == publication
    route = f"/api/projects/{test_project_id}/tasks/{task['id']}"
    response = client.get(route)
    assert response.status_code == 200
    assert response.json()['verification_result']['publication'] == publication
    context = client.get(f"{route}/context?format=json")
    assert context.status_code == 200
    assert context.json()['task']['verification_result']['publication'] == publication


def test_historical_publication_survives_new_acceptance_and_completion(test_project_id, cleanup_task):
    task = tasks.create_task(test_project_id, 'Historical receipt survives acceptance')
    cleanup_task(task['id'])
    tasks.update_task_status(task['id'], 'running')
    publication = {'source_commit': SHA, 'publication_complete': True,
                   'ci': {'state': 'success', 'sha': SHA, 'checks': []}}
    tasks.add_commit(task['id'], SHA, project_id=test_project_id, publication=publication)
    from app.storage.tasks.closeout import store_verification

    store_verification(task['id'], test_project_id, {
        'acceptance': {'state': 'success', 'source_commit': SHA},
    })
    completed = tasks.update_task_status(task['id'], 'completed')
    assert completed is not None
    assert completed['commits'] == [SHA]
    assert completed['verification_result']['publication'] == publication


def test_retired_commit_publication_cannot_write_task_receipt(tmp_path, test_project_id, cleanup_task):
    task = tasks.create_task(test_project_id, 'Rejected implicit publication')
    cleanup_task(task['id'])
    publication = {'source_commit': SHA, 'publication_complete': True,
                   'ci': {'state': 'success', 'sha': SHA, 'checks': []}}
    tasks.add_commit(task['id'], SHA, project_id=test_project_id, publication=publication)
    before = tasks.get_task(task['id'])
    with pytest.raises(commit_workflow.CommitError, match='st vcs publish'):
        commit_workflow.commit_repo(tmp_path, message='publish', task_id=task['id'], push=True)
    assert tasks.get_task(task['id']) == before


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
        'closeout': {'kind': 'local_closeout.v1', 'state': 'pending', 'request_id': 'obsolete-request'},
    })
    stored = tasks.update_task_status(task['id'], 'paused')
    assert stored is not None
    proof = stored['verification_result']
    assert proof['acceptance']['state'] == 'stale'
    assert proof['acceptance']['acceptance_artifact'] == '/retained/receipt.json'
    assert proof['deployment']['source_commit'] == SHA
    assert proof['closeout']['kind'] == 'lifecycle_closeout_history.v1'
    assert proof['closeout']['state'] == 'historical'
    assert proof['closeout']['previous_closeout'] == {
        'kind': 'local_closeout.v1', 'state': 'pending', 'request_id': 'obsolete-request',
    }
