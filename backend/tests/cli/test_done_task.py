from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer import Exit

from cli.commands.done_lifecycle import _reconstruct_snapshot_info
from cli.commands.done_task import _task_scope_paths, complete_task
from cli.lib.checkpoint_branches import resolve_task_branch


def test_st_client_exposes_get_task_completion_readiness() -> None:
    with patch("cli.config.get_config_optional") as mock_config, patch(
        "cli._client_base.httpx.Client"
    ) as mock_http_client:
        mock_config.return_value.api_base = "http://summitflow.test"
        mock_config.return_value.project_id = "summitflow"
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"ready": True, "gates": []}
        mock_http_client.return_value.get.return_value = response

        from cli.client import STClient

        client = STClient(require_project=False)
        result = client.get_task_completion_readiness("task-123")

    mock_http_client.return_value.get.assert_called_once_with(
        "http://summitflow.test/tasks/task-123/completion-readiness"
    )
    assert result == {"ready": True, "gates": []}


def test_run_smart_prereqs_auto_closes_unpassed_subtasks() -> None:
    client = MagicMock()
    client.get_subtasks.return_value = {
        "subtasks": [{"subtask_id": "1.1", "passes": False, "citations_status": "acknowledged"}]
    }
    client.get_task_completion_readiness.return_value = {"ready": True}

    with patch("cli.commands.done_task.sync_completed_subtasks") as mock_sync:
        mock_sync.return_value.synced = []
        from cli.commands.done_task import _run_smart_prereqs

        _run_smart_prereqs(client, "task-789", "summitflow")

    client.update_subtask.assert_called_once_with("task-789", "1.1", passes=True)


def test_run_smart_prereqs_auto_closes_subtasks_in_dependency_order() -> None:
    client = MagicMock()
    client.get_subtasks.return_value = {
        "subtasks": [
            {"subtask_id": "2.1", "passes": False, "depends_on": ["1.1"], "citations_status": "acknowledged"},
            {"subtask_id": "1.1", "passes": False, "citations_status": "acknowledged"},
            {"subtask_id": "3.1", "passes": False, "depends_on": ["2.1"], "citations_status": "acknowledged"},
        ]
    }
    client.get_task_completion_readiness.return_value = {"ready": True}

    with patch("cli.commands.done_task.sync_completed_subtasks") as mock_sync:
        mock_sync.return_value.synced = []
        from cli.commands.done_task import _run_smart_prereqs

        _run_smart_prereqs(client, "task-789", "summitflow")

    assert [call.args[1] for call in client.update_subtask.call_args_list] == ["1.1", "2.1", "3.1"]


def test_reconstruct_snapshot_info_defaults_missing_base_branch_to_main() -> None:
    client = MagicMock()
    client.get_task.return_value = {
        "status": "pending",
        "project_id": "summitflow",
        "base_branch": "",
        "created_at": "2026-04-23T00:00:00Z",
        "claimed_by": "worker-1",
    }
    expected_snapshot = {
        "task_id": "task-1",
        "project_id": "summitflow",
        "base_branch": "main",
    }

    with (
        patch(
            "cli.lib.checkpoint_branches.get_task_branches",
            return_value=[{"branch": "task-1/main", "type": "task"}],
        ),
        patch("cli.commands.done_lifecycle.save_snapshot_meta") as mock_save,
        patch("cli.commands.done_lifecycle.get_snapshot_info", return_value=expected_snapshot),
    ):
        result = _reconstruct_snapshot_info(client, "task-1")

    assert result == expected_snapshot
    assert mock_save.call_args.args[0].base_branch == "main"


def test_resolve_task_branch_prefers_st_commit_bookmark() -> None:
    with (
        patch("cli.lib.checkpoint_branches._get_repo_cwd", return_value="/repo"),
        patch(
            "cli.lib.checkpoint_branches._branch_exists",
            side_effect=lambda branch, _cwd: branch in {"task/task-1", "task-1/main"},
        ),
    ):
        assert resolve_task_branch("task-1", project_id="summitflow") == "task/task-1"


def test_local_commit_event_supports_linkage_before_separate_acceptance():
    from cli.commands.done_task import _task_has_published_commit_event
    with patch('app.storage.events.get_events_by_trace', return_value=[{'message': 'st commit commit=abcdef pushed=true'}]):
        assert _task_has_published_commit_event('task-123')


def test_missing_checkpoint_base_recovers_only_from_task_linked_direct_commit(tmp_path):
    import subprocess

    import typer

    from cli.commands.done_task import _run_diff_gate

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True,
        ).stdout.strip()

    git("init", "-q", "--initial-branch=main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    git("config", "core.hooksPath", "/dev/null")
    (tmp_path / "app.py").write_text("before\n")
    git("add", "app.py")
    git("commit", "-qm", "baseline")
    (tmp_path / "app.py").write_text("after\n")
    git("commit", "-qam", "task change")
    commit = git("rev-parse", "HEAD")

    with (
        patch("cli.commands.done_task.resolve_task_branch", return_value="missing/task-branch"),
        patch(
            "app.storage.events.get_events_by_trace",
            return_value=[{"message": f"st commit commit={commit} pushed=false"}],
        ),
    ):
        _run_diff_gate(str(tmp_path), "task-direct", "a-term", "main")

    with (
        patch("cli.commands.done_task.resolve_task_branch", return_value="missing/task-branch"),
        patch("app.storage.events.get_events_by_trace", return_value=[]),
        pytest.raises(typer.Exit),
    ):
        _run_diff_gate(str(tmp_path), "task-direct", "a-term", "main")


def test_verified_existing_remote_commit_can_support_closeout():
    from cli.commands.done_task import _task_has_published_commit_event
    with patch('app.storage.events.get_events_by_trace', return_value=[{'message': 'st commit commit=abcdef pushed=false publication_complete=true'}]):
        assert _task_has_published_commit_event('task-123')


@pytest.mark.parametrize("claimed_at, passes", [("2000-01-01T00:00:00+00:00", True), ("2100-01-01T00:00:00+00:00", False), (None, False)])
@pytest.mark.parametrize("history", ["initial", "amended_root", "amended_then_commit", "switched_then_amended", "missing_reflog", "empty_commit"])
def test_initial_repository_closeout_requires_post_claim_initial_reflog(tmp_path, monkeypatch, claimed_at, passes, history):
    import subprocess

    import typer

    from cli.commands.done_task import _run_diff_gate

    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True).stdout

    git("init", "-q", "--initial-branch=main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    git("config", "core.hooksPath", "/dev/null")
    (tmp_path / "app.py").write_text("print('bootstrap')\n")
    git("add", ".")
    if history == "empty_commit":
        git("rm", "--cached", "app.py")
        git("commit", "--allow-empty", "-qm", "initial")
    else:
        git("commit", "-qm", "initial")
    if history in {"amended_root", "amended_then_commit", "switched_then_amended"}:
        if history == "switched_then_amended":
            git("checkout", "-qb", "different-work")
        (tmp_path / "app.py").write_text("print('corrected bootstrap')\n")
        git("add", "app.py")
        git("commit", "--amend", "-qm", "correct initial release")
        if history == "amended_then_commit":
            (tmp_path / "app.py").write_text("print('next change')\n")
            git("add", "app.py")
            git("commit", "-qm", "continue implementation")
    if history == "missing_reflog":
        git("reflog", "expire", "--expire=all", "--all")
    passes = passes and history in {"initial", "amended_root", "amended_then_commit"}
    monkeypatch.setattr("cli.commands.done_task.resolve_task_branch", lambda *a, **k: "task-new/main")
    if passes:
        _run_diff_gate(str(tmp_path), "task-new", "test", "main", claimed_at=claimed_at)
    else:
        with pytest.raises(typer.Exit):
            _run_diff_gate(str(tmp_path), "task-new", "test", "main", claimed_at=claimed_at)


def test_task_scope_paths_uses_structured_files_only():
    assert _task_scope_paths({"description": "Inspect backend/app.py"}) == set()
    assert _task_scope_paths({"files_to_modify": ["app.py"], "context": {"files_to_modify": ["tests.py"]}}) == {"app.py", "tests.py"}


@pytest.mark.parametrize("snapshot", [None, {"project_id": "example", "base_branch": "main"}])
def test_administrative_completion_needs_no_fabricated_diff(snapshot, monkeypatch):
    client = MagicMock()
    client.get_task.return_value = {"status": "running", "context": {}, "project_id": "example"}
    client.get_task_completion_readiness.return_value = {"ready": True}
    client.get_subtasks.return_value = {"subtasks": []}
    monkeypatch.setattr("app.services.task_closeout.get_closeout", lambda _: None)
    monkeypatch.setattr("cli.commands.done_task.get_snapshot_info", lambda _: snapshot)
    monkeypatch.setattr("cli.commands.done_task._checkpoint_repo_root", lambda _: "/repo")
    claim = {"project_id": "example", "claimed_by": "fixture", "claimed_at": "claim"}
    monkeypatch.setattr("cli.commands.done_task._owned_completion_claim", lambda *a: claim)
    close = MagicMock(return_value={"status": "completed", "project_id": "example", "verification_result": {}})
    monkeypatch.setattr("app.storage.tasks.update_task_status", close)
    monkeypatch.setattr("app.storage.tasks.closeout.cleanup_completed_checkpoint", lambda *a, **kw: (kw["cleanup"](), True)[1])
    cleanup = MagicMock()
    monkeypatch.setattr("cli.commands.done_task._capture_and_remove_snapshot", cleanup)
    commit = MagicMock(side_effect=AssertionError("No fabricated change"))
    monkeypatch.setattr("cli.commands.done_task.commit_repo", commit)
    result = complete_task(client, "task-admin")
    assert result["action"] == "completed"
    close.assert_called_once_with("task-admin", "completed", expected_worker="fixture",
        expected_claimed_at="claim", expected_project_id="example")
    client.close_task.assert_not_called()
    client.acknowledge_no_citations.assert_not_called()
    commit.assert_not_called()
    assert cleanup.call_count == int(snapshot is not None)


def test_record_only_cannot_bypass_declared_readiness(monkeypatch):
    client = MagicMock()
    client.get_task.return_value = {"status": "running", "context": {"files_to_modify": ["app.py"]}}
    client.get_task_completion_readiness.return_value = {"ready": False, "gates": [{"gate": "acceptance"}]}
    monkeypatch.setattr("app.services.task_closeout.get_closeout", lambda _: None)
    monkeypatch.setattr("cli.commands.done_task.get_snapshot_info", lambda _: None)
    with pytest.raises(Exit):
        complete_task(client, "task-implementation", admin=True)
    client.close_task.assert_not_called()


@pytest.mark.parametrize("scope_key", ["files_to_modify", "files_to_create"])
def test_record_only_rejects_implementation_with_retained_success(monkeypatch, scope_key):
    client = MagicMock()
    client.get_task.return_value = {"status": "running", "context": {scope_key: ["app.py"]},
                                  "verification_result": {"acceptance": {"state": "success", "source_commit": "a" * 40}}}
    client.get_task_completion_readiness.return_value = {"ready": True, "gates": []}
    monkeypatch.setattr("app.services.task_closeout.get_closeout", lambda _: None)
    monkeypatch.setattr("cli.commands.done_task.get_snapshot_info", lambda _: {"base_commit": "a" * 40})
    cleanup = MagicMock()
    monkeypatch.setattr("cli.commands.done_task._complete_admin", cleanup)

    with pytest.raises(Exit) as failure:
        complete_task(client, "task-implementation", admin=True)

    assert failure.value.exit_code == 2
    client.close_task.assert_not_called()
    cleanup.assert_not_called()


def test_historical_remote_wait_does_not_resume_or_block_local_completion(monkeypatch):
    from cli.commands import done_task
    client = MagicMock()
    client.get_task.return_value = {"status": "running", "project_id": "example", "files_to_modify": ["app.py"]}
    monkeypatch.setattr("app.services.task_closeout.get_closeout", lambda _: {"state": "pending", "require_remote_confirmation": True})
    remote = MagicMock(side_effect=AssertionError("No remote closeout"))
    monkeypatch.setattr("app.services.task_closeout.resume_closeout", remote)
    monkeypatch.setattr(done_task, "get_snapshot_info", lambda _: {"project_id": "example", "base_branch": "main"})
    monkeypatch.setattr(done_task, "_complete_with_snapshot", lambda *args, **kwargs: {"action": "completed"})
    assert complete_task(client, "task-legacy")["action"] == "completed"
    remote.assert_not_called()


def test_local_pending_cleanup_resumes_without_checkpointing(monkeypatch):
    monkeypatch.setattr("app.services.task_closeout.get_closeout", lambda _: {"kind": "local_closeout.v1", "state": "pending"})
    resume = MagicMock(return_value={"action": "completed"})
    monkeypatch.setattr("app.services.task_closeout.resume_closeout", resume)
    client = MagicMock()
    assert complete_task(client, "task-local")["action"] == "completed"
    resume.assert_called_once_with("task-local", explicit=True)
    client.get_task.assert_not_called()
