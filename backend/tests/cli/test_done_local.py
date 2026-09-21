"""Default task completion must never make publication a prerequisite."""
from unittest.mock import MagicMock, patch

from cli.commands import done_task


def test_commit_during_closeout_is_local():
    result = {"status": "SUCCESS", "sha": "a" * 40, "pushed": False}
    with patch.object(done_task, "commit_repo", return_value=result) as commit, patch("app.storage.events.log_task_event"):
        done_task._commit_active_task_work("/repo", "task-local", "local change")
    assert commit.call_args.kwargs["push"] is False


def test_closeout_persists_local_acceptance_without_publisher(tmp_path):
    receipt = {"state": "success", "source_commit": "a" * 40}
    with (
        patch.object(done_task, "get_project_root_path", return_value=str(tmp_path)),
        patch("cli.lib.acceptance.accept_revision", return_value=receipt) as accept,
        patch("cli.lib.commit_workflow.run_git", return_value=MagicMock(returncode=0, stdout="a" * 40)),
        patch("app.storage.tasks.closeout.store_verification") as store,
        patch("cli.lib.publish_workflow.publish_git", side_effect=AssertionError("GitHub is unavailable")),
    ):
        done_task._accept_completed_work("task-local", "summitflow")
    accept.assert_called_once()
    store.assert_called_once_with("task-local", "summitflow", {"acceptance": receipt})
