"""Default task completion must never make publication a prerequisite."""
import subprocess
from unittest.mock import Mock, patch

from cli.commands import done_task


def test_commit_during_closeout_is_local():
    result = {"status": "SUCCESS", "sha": "a" * 40, "pushed": False}
    with patch.object(done_task, "commit_repo", return_value=result) as commit, patch("app.storage.events.log_task_event"):
        done_task._commit_active_task_work("/repo", "task-local", "local change", paths=("app.py",))
    assert commit.call_args.kwargs["push"] is False


def test_closeout_persists_local_acceptance_without_publisher(tmp_path, local_gate_tools):
    from cli.lib.task_completion_adapter import accept_owned_task_work

    receipt = accepted_source(tmp_path)
    with (
        patch("app.storage.task_spirit.get_task_spirit", return_value=None),
        patch("app.storage.tasks.closeout.store_owned_acceptance", return_value=True) as store,
        patch("cli.lib.publish_workflow.publish_git", side_effect=AssertionError("GitHub is unavailable")),
    ):
        result = accept_owned_task_work(tmp_path, "task-local", "summitflow", paths=("owned.py",), acceptance_receipt=receipt,
            claim={"id": "task-local", "project_id": "summitflow", "claimed_by": "fixture", "claimed_at": "claim", "verification_result": {}})
    assert dict(result) == receipt
    store.assert_called_once_with("task-local", "summitflow", receipt, expected_worker="fixture", expected_claimed_at="claim", expected_acceptance={})


def test_retained_acceptance_reused_with_foreign_work_present(tmp_path, monkeypatch, local_gate_tools):
    from cli.lib.task_completion_adapter import accept_owned_task_work

    receipt = accepted_source(tmp_path)
    monkeypatch.setattr("app.storage.task_spirit.get_task_spirit", lambda _: None)
    store = Mock(return_value=True)
    monkeypatch.setattr("app.storage.tasks.closeout.store_owned_acceptance", store)
    (tmp_path / "foreign.py").write_text("foreign WIP")
    result = accept_owned_task_work(tmp_path, "task-local", "example", paths=("owned.py",),
        claim={"id": "task-local", "project_id": "example", "claimed_by": "fixture", "claimed_at": "claim", "verification_result": {"acceptance": receipt}})
    assert result.reused is True
    assert dict(result) == receipt
    assert (tmp_path / "foreign.py").read_text() == "foreign WIP"


def accepted_source(repo):
    from cli.lib.acceptance import accept_revision
    from cli.lib.acceptance_coordinator import validate_source_receipt

    for args in (("init", "-q"), ("config", "user.name", "Fixture"), ("config", "user.email", "fixture@example.invalid")):
        subprocess.run(["git", *args], cwd=repo, check=True)
    (repo / "owned.py").write_text("value = 1\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "source"], cwd=repo, check=True)
    proof = accept_revision(repo, sha="HEAD", scope=("owned.py",), task_id="task-local", execution_basis="isolated",
                            runner=lambda command, cwd: subprocess.CompletedProcess(command, 0, "fixture full gate", ""))
    return validate_source_receipt(repo, proof).reference.to_dict()
