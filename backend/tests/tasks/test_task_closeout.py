"""Completion continuation retains immutable work and honors lifecycle changes."""
from unittest.mock import Mock

import pytest

from app.services import task_closeout as closeout
from app.storage import tasks
from app.storage.tasks.closeout import closeout_lock, store_closeout
from cli.lib import publish_workflow

SHA = 'a' * 40


@pytest.fixture
def pending_task(test_project_id, cleanup_task, monkeypatch, tmp_path):
    task = tasks.create_task(test_project_id, 'Resume exact-source closeout')
    cleanup_task(task['id'])
    tasks.update_task(task['id'], verification_result={'independent': {'retained': True}})
    closeout.request_closeout(task['id'], test_project_id, source_sha=SHA, message='Finish tested work')
    monkeypatch.setattr('app.storage.projects.get_project_root_path', lambda _pid: str(tmp_path))
    monkeypatch.setattr('cli.lib.execution_context.resolve_checkout_project_id', lambda _root: test_project_id)
    monkeypatch.setattr('cli.client.STClient', Mock())
    monkeypatch.setattr('cli.commands.done_task._auto_verify_readiness', Mock())
    monkeypatch.setattr('cli.commands.done._release_task_leases', Mock())
    return task


def evidence(state='pending', sha=SHA):
    return {'status': {'pending': 'PENDING', 'success': 'SUCCESS', 'failed': 'BLOCKED'}[state],
            'sha': SHA, 'publication_complete': state == 'success',
            'reason': f'remote_ci_{state}', 'ci': {'state': state, 'sha': sha, 'checks': []}}


def test_pending_to_complete_preserves_source_and_other_receipts(pending_task, monkeypatch, tmp_path):
    publisher = Mock(side_effect=[evidence(), evidence('success')])
    monkeypatch.setattr(publish_workflow, 'publish_git', publisher)
    # Later work exists, but continuation may neither commit it nor choose its HEAD.
    (tmp_path / 'later-user-work').write_text('uncommitted')
    monkeypatch.setattr('cli.lib.commit_workflow.commit_repo', Mock(side_effect=AssertionError('must not commit')))
    tid = pending_task['id']
    assert closeout.resume_closeout(tid)['action'] == 'pending'
    assert closeout.resume_closeout(tid)['action'] == 'completed'
    assert closeout.resume_closeout(tid)['action'] == 'completed'
    assert publisher.call_count == 2
    assert all(call.kwargs['sha'] == SHA and call.kwargs['resume'] for call in publisher.call_args_list)
    stored = tasks.get_task(tid)
    assert stored and stored['status'] == 'completed'
    assert stored['verification_result']['independent'] == {'retained': True}
    assert stored['verification_result']['publication']['source_commit'] == SHA
    assert stored['verification_result']['closeout']['state'] == 'complete'
    assert (tmp_path / 'later-user-work').read_text() == 'uncommitted'


def test_failure_is_retained_and_not_automatically_retried(pending_task, monkeypatch):
    publisher = Mock(return_value=evidence('failed'))
    monkeypatch.setattr(publish_workflow, 'publish_git', publisher)
    tid = pending_task['id']
    assert closeout.resume_closeout(tid)['action'] == 'blocked'
    assert closeout.resume_closeout(tid)['action'] == 'blocked'
    assert publisher.call_count == 1
    publisher.return_value = evidence('success')
    assert closeout.resume_closeout(tid, explicit=True)['action'] == 'completed'


def test_mismatched_ci_cannot_complete(pending_task, monkeypatch):
    monkeypatch.setattr(publish_workflow, 'publish_git', Mock(return_value=evidence('success', 'b' * 40)))
    result = closeout.resume_closeout(pending_task['id'])
    assert result['action'] == 'blocked'
    assert 'CI revision' in result['reason']
    stored = tasks.get_task(pending_task['id'])
    assert stored and stored['status'] == 'pending'


def test_pause_during_remote_observation_cannot_resurrect_request(pending_task, monkeypatch):
    def pause(*args, **kwargs):
        tasks.update_task_status(pending_task['id'], 'paused')
        return evidence('success')
    monkeypatch.setattr(publish_workflow, 'publish_git', pause)
    assert closeout.resume_closeout(pending_task['id'])['action'] == 'skipped'
    stored = tasks.get_task(pending_task['id'])
    assert stored and stored['status'] == 'paused'
    assert closeout.get_closeout(pending_task['id']) is None


def test_pause_at_final_status_boundary_cannot_close(pending_task, monkeypatch):
    monkeypatch.setattr(publish_workflow, 'publish_git', Mock(return_value=evidence('success')))
    monkeypatch.setattr('cli.commands.done_task._auto_verify_readiness',
                        lambda *_args: tasks.update_task_status(pending_task['id'], 'paused'))
    assert closeout.resume_closeout(pending_task['id'])['action'] == 'skipped'
    stored = tasks.get_task(pending_task['id'])
    assert stored and stored['status'] == 'paused'


def test_expired_claim_preserves_queued_closeout_but_new_claim_cancels_it(pending_task):
    tid = pending_task['id']
    # Existing claim-expiry semantics, with an already expired test claim.
    tasks.claim_task(tid, 'test-worker', lock_duration_minutes=-1)
    closeout.request_closeout(tid, pending_task['project_id'], source_sha=SHA, message='done')
    tasks.reset_expired_claims()
    queued = closeout.get_closeout(tid)
    assert queued and queued['state'] == 'pending'
    tasks.claim_task(tid, 'new-worker')
    assert closeout.get_closeout(tid) is None


def test_concurrent_continuation_does_not_publish(pending_task, monkeypatch):
    publisher = Mock(side_effect=AssertionError('another closeout holds the lock'))
    monkeypatch.setattr(publish_workflow, 'publish_git', publisher)
    with closeout_lock(pending_task['id']) as acquired:
        assert acquired
        assert closeout.resume_closeout(pending_task['id'])['reason'] == 'closeout_in_progress'
    publisher.assert_not_called()


def test_crash_after_status_completion_resumes_cleanup_without_publishing(pending_task, monkeypatch):
    tid = pending_task['id']
    intent = closeout.get_closeout(tid)
    assert intent is not None
    intent['publication'] = evidence('success')
    store_closeout(tid, pending_task['project_id'], intent)
    tasks.update_task_status(tid, 'completed', validate_transition=False)
    publisher = Mock(side_effect=AssertionError('successful publication already retained'))
    monkeypatch.setattr(publish_workflow, 'publish_git', publisher)
    assert closeout.resume_closeout(tid)['action'] == 'completed'
    completed = closeout.get_closeout(tid)
    assert completed and completed['state'] == 'complete'
    publisher.assert_not_called()


def test_pending_closeout_is_not_offered_as_fresh_implementation_work(pending_task):
    tasks.update_task(pending_task['id'], priority=0)
    ready = tasks.list_ready_tasks(pending_task['project_id'], limit=10000)
    assert pending_task['id'] not in {task['id'] for task in ready}


def test_pending_closeout_is_excluded_from_automatic_and_immediate_pickup(pending_task):
    from app.tasks.autonomous.pickup_guards import check_task_dispatchable
    from app.tasks.autonomous.pickup_queries import get_queued_autonomous_tasks

    tasks.update_task(pending_task['id'], priority=0, execution_mode='autonomous')
    queued = get_queued_autonomous_tasks(pending_task['project_id'], limit=10000)
    assert pending_task['id'] not in {task['id'] for task in queued}
    task = tasks.get_task(pending_task['id'])
    assert task is not None
    result = check_task_dispatchable(task)
    assert result and result['reason'] == 'publication_closeout_pending'
