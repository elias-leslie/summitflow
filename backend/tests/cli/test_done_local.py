"""Default task completion must never make publication a prerequisite."""
from unittest.mock import MagicMock, patch

from cli.commands import done_task


def test_commit_during_closeout_is_local():
    result = {"status": "SUCCESS", "sha": "a" * 40, "pushed": False}
    with patch.object(done_task, "commit_repo", return_value=result) as commit, patch("app.storage.events.log_task_event"):
        done_task._commit_active_task_work("/repo", "task-local", "local change", paths=("app.py",))
    assert commit.call_args.kwargs["push"] is False


def test_closeout_persists_local_acceptance_without_publisher(tmp_path):
    receipt = {"state": "success", "source_commit": "a" * 40}
    with (
        patch.object(done_task, "get_project_root_path", return_value=str(tmp_path)),
        patch("cli.lib.acceptance.accept_revision", return_value=receipt) as accept,
        patch("cli.lib.commit_workflow.run_git", return_value=MagicMock(returncode=0, stdout="a" * 40)),
        patch("cli.commands.done_task._owned_completion_claim", return_value={"project_id": "summitflow", "claimed_by": "fixture", "claimed_at": "claim", "verification_result": {}}),
        patch("app.storage.tasks.closeout.store_owned_acceptance", return_value=True) as store,
        patch("cli.lib.publish_workflow.publish_git", side_effect=AssertionError("GitHub is unavailable")),
    ):
        done_task._accept_completed_work("task-local", "summitflow")
    accept.assert_called_once()
    store.assert_called_once_with("task-local", "summitflow", receipt, expected_worker="fixture", expected_claimed_at="claim", expected_acceptance={})


def test_retained_acceptance_reused_with_foreign_work_present(tmp_path, monkeypatch):
    from contextlib import nullcontext

    from cli.lib import acceptance

    receipt = {"state": "success", "source_commit": "a" * 40}
    monkeypatch.setattr(done_task, "get_project_root_path", lambda _: str(tmp_path))
    monkeypatch.setattr(done_task, "_owned_completion_claim", lambda *a: {"project_id": "example", "claimed_by": "fixture", "claimed_at": "claim", "verification_result": {"acceptance": receipt}})
    monkeypatch.setattr(acceptance, "repo_lock", lambda *a, **kw: nullcontext())
    monkeypatch.setattr(done_task, "_selected_work_is_clean", lambda *a, **kw: True)
    monkeypatch.setattr("cli.commands.done_task_acceptance.require_scope_matches_revision", MagicMock())
    validator = MagicMock(return_value=receipt)
    monkeypatch.setattr(acceptance, "validate_acceptance_receipt", validator)
    rerun = MagicMock(side_effect=AssertionError("Valid full acceptance reused"))
    monkeypatch.setattr(acceptance, "accept_revision", rerun)
    store = MagicMock(return_value=True)
    monkeypatch.setattr("app.storage.tasks.closeout.store_owned_acceptance", store)
    (tmp_path / "foreign.py").write_text("foreign WIP")
    result = done_task._accept_completed_work("task-local", "example", paths=("owned.py",))
    assert result["reused"] is True
    assert validator.call_args.kwargs["sha"] == receipt["source_commit"]
    assert (tmp_path / "foreign.py").read_text() == "foreign WIP"
    rerun.assert_not_called()
