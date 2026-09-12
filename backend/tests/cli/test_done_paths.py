"""Task closeout selection must preserve unrelated checkout and index state."""
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
import typer
from typer.testing import CliRunner

from cli.commands import done, done_task
from cli.lib import commit_workflow


def test_done_accepts_repeatable_path_aliases(monkeypatch):
    client = Mock()
    client.get_task.return_value = {'status': 'running', 'project_id': 'example'}
    monkeypatch.setattr(done, 'STClient', Mock(return_value=client))
    monkeypatch.setattr(done, 'preflight', Mock())
    monkeypatch.setattr(done, '_release_task_leases', Mock())
    complete = Mock(return_value={})
    monkeypatch.setattr(done, 'complete_task', complete)
    result = CliRunner().invoke(done.app, ['task-1', '--path', 'src', '--paths', 'tests'])
    assert result.exit_code == 0, result.output
    assert complete.call_args.kwargs['paths'] == ('src', 'tests')


def test_done_rejects_path_selection_for_subtask_before_api(monkeypatch):
    client = Mock()
    monkeypatch.setattr(done, 'STClient', client)
    result = CliRunner().invoke(done.app, ['1.1', '--task', 'task-1', '--path', 'src'])
    assert result.exit_code != 0
    assert 'only apply to task completion' in result.output
    client.assert_not_called()


@pytest.mark.parametrize('has_snapshot', [True, False])
@pytest.mark.parametrize('gate_passes', [True, False])
def test_scoped_done_preserves_unrelated_index_and_worktree(tmp_path: Path, monkeypatch, has_snapshot, gate_passes):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=tmp_path, text=True).strip()

    git('init', '-q', '--initial-branch=main')
    git('config', 'user.name', 'Test')
    git('config', 'user.email', 'test@example.invalid')
    for name in ('task.txt', 'other.txt', '.index.yaml'):
        (tmp_path / name).write_text('before')
    git('add', '.')
    git('commit', '-qm', 'baseline')
    (tmp_path / 'task.txt').write_text('task work')
    (tmp_path / 'other.txt').write_text('unrelated staged work')
    (tmp_path / '.index.yaml').write_text('unrelated host metadata')
    git('add', 'other.txt')
    client = Mock()
    client.get_task.return_value = {'status': 'running', 'project_id': 'example'}
    client.get_task_completion_readiness.return_value = {'ready': True}
    snapshot = {'project_id': 'example', 'base_branch': 'main', 'base_commit': git('rev-parse', 'HEAD')}
    monkeypatch.setattr(done_task, 'get_snapshot_info', lambda _: snapshot if has_snapshot else None)
    monkeypatch.setattr(done_task, '_reconstruct_snapshot_info', lambda *args: None)
    monkeypatch.setattr(done_task, '_checkpoint_repo_root', lambda _: str(tmp_path))
    monkeypatch.setattr(done_task, '_run_smart_prereqs', Mock())
    monkeypatch.setattr(done_task, '_run_diff_gate', Mock())
    capture_snapshot = Mock()
    monkeypatch.setattr(done_task, '_capture_and_remove_snapshot', capture_snapshot)
    monkeypatch.setattr(done_task, '_task_has_published_commit_event', lambda _: False)
    monkeypatch.setattr(done_task, '_task_with_export_context', lambda *args: client.get_task.return_value)
    monkeypatch.setattr('app.storage.events.log_task_event', Mock())
    checks = Mock(return_value=(gate_passes, 'test gate failed'))
    monkeypatch.setattr(commit_workflow, 'run_checks', checks)
    monkeypatch.setattr(commit_workflow, 'publish_git', lambda _repo, *, sha, **_kwargs: {
        'status': 'SUCCESS', 'publication_complete': True,
        'ci': {'state': 'success', 'sha': sha, 'checks': []},
    })
    monkeypatch.setattr('cli.lib.execution_context.resolve_checkout_project_id', lambda _repo: 'example')
    monkeypatch.setattr('app.storage.tasks.add_commit', Mock(return_value={'id': 'task-1'}))
    publications = []

    def publish(task, project, *, paths=()):
        publications.append(paths)
        commit_workflow.commit_git_revision(tmp_path, message='publish', paths=paths)

    monkeypatch.setattr(done_task, '_publish_completed_work', publish)
    stash = Mock(side_effect=AssertionError('must not move unrelated work'))
    monkeypatch.setattr(done_task, 'git_stash_push', stash)
    if not gate_passes:
        with pytest.raises(typer.Exit):
            done_task.complete_task(client, 'task-1', paths=('task.txt',))
        assert git('rev-parse', 'HEAD') == snapshot['base_commit']
        assert git('diff', '--cached', '--name-only') == 'other.txt'
        assert (tmp_path / '.index.yaml').read_text() == 'unrelated host metadata'
        client.update_status.assert_not_called()
        capture_snapshot.assert_not_called()
        return
    result = done_task.complete_task(client, 'task-1', paths=('task.txt',))
    assert result['action'] == 'completed'
    assert git('show', '--format=', '--name-only', 'HEAD') == 'task.txt'
    assert git('diff', '--cached', '--name-only') == 'other.txt'
    assert (tmp_path / '.index.yaml').read_text() == 'unrelated host metadata'
    assert (tmp_path / 'other.txt').read_text() == 'unrelated staged work'
    assert publications == [('task.txt',)]
    checks.assert_called()
    stash.assert_not_called()



def test_final_publish_subprocess_receives_repeated_paths(tmp_path, monkeypatch):
    monkeypatch.setattr('app.storage.projects.get_project_root_path', lambda _: str(tmp_path))
    run = Mock(return_value=subprocess.CompletedProcess([], 0, '{"status":"SUCCESS","publication_complete":true}', ''))
    monkeypatch.setattr(done_task.subprocess, 'run', run)
    monkeypatch.setattr(done_task.shutil, 'which', lambda _: '/test/st')
    monkeypatch.setattr(done_task, 'cleanup_completed_bookmark', Mock())
    done_task._publish_completed_work('task-1', 'example', paths=('src', 'tests'))
    assert run.call_args.args[0][-4:] == ['--paths', 'src', '--paths', 'tests']
