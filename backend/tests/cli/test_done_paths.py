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


@pytest.mark.parametrize("selected", [True, False])
def test_done_forwards_acceptance_with_explicit_or_established_paths(tmp_path, monkeypatch, selected):
    client = Mock()
    client.get_task.return_value = {"status": "running", "project_id": "example"}
    monkeypatch.setattr(done, "STClient", Mock(return_value=client))
    monkeypatch.setattr(done, "preflight", Mock())
    monkeypatch.setattr(done, "_release_task_leases", Mock())
    monkeypatch.setattr("app.storage.projects.get_project_root_path", lambda _: str(tmp_path))
    receipt = {"state": "success"}
    monkeypatch.setattr("cli.lib.completion_evidence.load_completion_evidence", Mock(return_value={"acceptance": receipt}))
    monkeypatch.setattr(done_task, "_owned_completion_claim", lambda *a: {"project_id": "example", "claimed_by": "fixture", "claimed_at": "claim", "verification_result": {}})
    stored = Mock(return_value=True)
    monkeypatch.setattr("app.storage.tasks.closeout.store_owned_verification", stored)
    complete = Mock(return_value={})
    monkeypatch.setattr(done, "complete_task", complete)
    arguments = ["task-1", "--evidence", str(tmp_path / "evidence.json")]
    if selected:
        arguments.extend(["--paths", "src"])
    result = CliRunner().invoke(done.app, arguments)
    assert result.exit_code == 0, result.output
    assert complete.call_args.kwargs == {"paths": ("src",) if selected else (), "acceptance_receipt": receipt}
    stored.assert_called_once()


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
    renew_claim = Mock(return_value={'id': 'task-1', 'status': 'running'})
    monkeypatch.setattr(commit_workflow, 'renew_owned_claim', renew_claim)
    publish = Mock(side_effect=AssertionError('local completion must not publish'))
    monkeypatch.setattr('cli.lib.publish_workflow.publish_git', publish)
    monkeypatch.setattr('cli.lib.execution_context.resolve_checkout_project_id', lambda _repo: 'example')
    monkeypatch.setattr('app.storage.tasks.add_commit', Mock(return_value={'id': 'task-1'}))
    acceptances = []

    def accept(task, project, *, paths=()):
        acceptances.append(paths)

    monkeypatch.setattr(done_task, '_accept_completed_work', accept)
    monkeypatch.setattr(done_task, '_finish_local_completion', Mock(return_value={'action': 'completed'}))
    stash = Mock(side_effect=AssertionError('must not move unrelated work'))
    monkeypatch.setattr('cli.commands.done_git.git_stash_push', stash)
    if not gate_passes:
        with pytest.raises(typer.Exit):
            done_task.complete_task(client, 'task-1', paths=('task.txt',))
        assert git('rev-parse', 'HEAD') == snapshot['base_commit']
        assert git('diff', '--cached', '--name-only') == 'other.txt'
        assert (tmp_path / '.index.yaml').read_text() == 'unrelated host metadata'
        client.update_status.assert_not_called()
        capture_snapshot.assert_not_called()
        publish.assert_not_called()
        renew_claim.assert_called_once_with(tmp_path, 'task-1')
        return
    result = done_task.complete_task(client, 'task-1', paths=('task.txt',))
    assert result['action'] == 'completed'
    assert git('show', '--format=', '--name-only', 'HEAD') == 'task.txt'
    assert git('diff', '--cached', '--name-only') == 'other.txt'
    assert (tmp_path / '.index.yaml').read_text() == 'unrelated host metadata'
    assert (tmp_path / 'other.txt').read_text() == 'unrelated staged work'
    assert acceptances == [('task.txt',)]
    checks.assert_called()
    renew_claim.assert_called_once_with(tmp_path, 'task-1')
    stash.assert_not_called()
    publish.assert_not_called()




@pytest.mark.parametrize("has_snapshot", [True, False])
@pytest.mark.parametrize("inference", ["declaration", "create", "lease"])
def test_automatic_done_selects_only_established_paths(tmp_path, monkeypatch, has_snapshot, inference):
    from datetime import UTC, datetime

    from cli.commands.done_task_scope import closeout_paths
    from cli.lib.leases import Lease

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "owned.py").write_text("task work")
    (tmp_path / "foreign.py").write_text("foreign work")
    now = datetime.now(UTC).isoformat()
    current = Lease("own", "worker", "worker", "session", "test", [str(tmp_path / "owned.py")], "task-1", now, now)
    foreign = Lease("foreign", "other", "other", "other", "test", [str(tmp_path / "foreign.py")], "task-other", now, now)
    monkeypatch.setattr("cli.lib.leases.identify_agent", lambda: ("worker", "worker", "session", "test"))
    monkeypatch.setattr("cli.lib.leases.list_active", lambda _: [current, foreign])
    task = {"context": {"files_to_modify" if inference == "declaration" else "files_to_create": ["owned.py"]}} if inference != "lease" else {}
    assert closeout_paths(str(tmp_path), "task-1", task, project_id="example") == ("owned.py",)


def test_prose_mentions_do_not_authorize_checkpoint(tmp_path, monkeypatch):
    from cli.commands.done_task_scope import closeout_paths
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "mentioned.py").write_text("unrelated work")
    monkeypatch.setattr("cli.lib.leases.list_active", lambda _: [])
    with pytest.raises(ValueError, match="Rerun st done task-1 --paths"):
        closeout_paths(str(tmp_path), "task-1", {"description": "Review mentioned.py"}, project_id="example")


@pytest.mark.parametrize("path", ["../foreign.py", ":(glob)**", "*.py"])
def test_checkpoint_scope_rejects_paths_outside_literal_ownership(tmp_path, monkeypatch, path):
    from cli.commands.done_task_scope import closeout_paths
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setattr("cli.lib.leases.list_active", lambda _: [])
    with pytest.raises(ValueError):
        closeout_paths(str(tmp_path), "task-1", {}, project_id="example", paths=(path,))


def test_explicit_foreign_lease_is_preserved(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from cli.commands.done_task_scope import closeout_paths
    from cli.lib.leases import Lease
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "foreign.py").write_text("foreign work")
    now = datetime.now(UTC).isoformat()
    lease = Lease("foreign", "other", "other", "other", "test", [str(tmp_path / "foreign.py")], "task-other", now, now)
    monkeypatch.setattr("cli.lib.leases.list_active", lambda _: [lease])
    with pytest.raises(ValueError, match="another active owner"):
        closeout_paths(str(tmp_path), "task-1", {}, project_id="example", paths=("foreign.py",))
    assert (tmp_path / "foreign.py").read_text() == "foreign work"
