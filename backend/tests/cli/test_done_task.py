from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from typer import Exit

from cli.commands.done_lifecycle import _reconstruct_snapshot_info
from cli.commands.done_task import _task_scope_paths, complete_task
from cli.lib.checkpoint_branches import resolve_task_branch


def test_complete_task_missing_checkpoint_completed_task_is_idempotent_and_publishes() -> None:
    client = MagicMock()
    client.get_task.return_value = {
        "status": "completed",
        "project_id": "summitflow",
        "base_branch": "main",
    }

    with (
        patch("cli.commands.done_task.get_snapshot_info", return_value=None),
        patch("cli.commands.done_task._reconstruct_snapshot_info", return_value=None),
        patch("cli.commands.done_task.is_working_tree_clean", return_value=True),
        patch("cli.commands.done_task._publish_completed_work") as mock_publish,
    ):
        result = complete_task(client, "task-123")

    mock_publish.assert_called_once_with("task-123", "summitflow")
    assert result["merged"] is False
    assert result["snapshot_removed"] is True


def test_complete_task_missing_checkpoint_failed_task_is_idempotent() -> None:
    client = MagicMock()
    client.get_task.return_value = {
        "status": "failed",
        "project_id": "summitflow",
        "base_branch": "main",
    }

    with (
        patch("cli.commands.done_task.get_snapshot_info", return_value=None),
        patch("cli.commands.done_task._reconstruct_snapshot_info", return_value=None),
        patch("cli.commands.done_task.is_working_tree_clean", return_value=True),
    ):
        result = complete_task(client, "task-456")

    assert result["merged"] is False
    assert result["snapshot_removed"] is True


def test_complete_task_admin_requires_completion_readiness() -> None:
    client = MagicMock()
    client.get_task_completion_readiness.return_value = {
        "ready": False,
        "gates": [{"gate": "subtasks"}],
    }

    with (
        patch("cli.commands.done_task.get_snapshot_info", return_value=None),
        patch("cli.commands.done_task.output_error") as mock_output,
        pytest.raises(Exit) as exc_info,
    ):
        complete_task(client, "task-123", admin=True)

    assert exc_info.value.exit_code == 1
    client.close_task.assert_not_called()
    assert "Task not ready to complete: subtasks" in mock_output.call_args.args[0]


def test_complete_task_admin_closes_when_completion_ready() -> None:
    client = MagicMock()
    client.get_task_completion_readiness.return_value = {"ready": True, "gates": []}

    with patch("cli.commands.done_task.get_snapshot_info", return_value=None):
        result = complete_task(client, "task-123", admin=True)

    client.close_task.assert_called_once_with("task-123", reason=None, skip_gates=True)
    assert result["merged"] is False


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


def test_complete_task_missing_checkpoint_pending_task_exits_with_guidance() -> None:
    client = MagicMock()
    client.get_task.return_value = {
        "status": "pending",
        "project_id": "summitflow",
        "base_branch": "main",
    }

    with (
        patch("cli.commands.done_task.get_snapshot_info", return_value=None),
        patch("cli.commands.done_task._reconstruct_snapshot_info", return_value=None),
        patch("cli.commands.done_task.output_error") as mock_output,
        pytest.raises(Exit) as exc_info,
    ):
        complete_task(client, "task-789")

    assert exc_info.value.exit_code == 1
    assert "active task" in mock_output.call_args.args[0]


def test_complete_task_missing_checkpoint_active_task_closes_after_pushed_commit_event() -> None:
    client = MagicMock()
    client.get_task.return_value = {
        "status": "pending",
        "project_id": "summitflow",
        "base_branch": "main",
    }

    with (
        patch("cli.commands.done_task.get_snapshot_info", return_value=None),
        patch("cli.commands.done_task._reconstruct_snapshot_info", return_value=None),
        patch("cli.commands.done_task._checkpoint_repo_root", return_value="/repo"),
        patch("cli.commands.done_task.is_working_tree_clean", return_value=True),
        patch("cli.commands.done_task._task_has_published_commit_event", return_value=True),
        patch("cli.commands.done_task.resolve_task_branch", return_value="task/task-789"),
        patch("cli.commands.done_task.check_diff_gate") as mock_diff_gate,
        patch("cli.commands.done_task.merge_task_branch") as mock_merge,
        patch("cli.commands.done_task._publish_completed_work") as mock_publish,
        patch("cli.commands.done_task._run_smart_prereqs") as mock_prereqs,
        patch("cli.commands.done_task.output_success"),
    ):
        mock_diff_gate.return_value = MagicMock(passed=True, summary="ok")
        result = complete_task(client, "task-789")

    mock_diff_gate.assert_called_once_with(
        "/repo",
        head_ref="task/task-789",
        base_ref="main",
    )
    mock_prereqs.assert_called_once_with(
        client, "task-789", "summitflow", merge_subtask_branches=False
    )
    mock_merge.assert_not_called()
    mock_publish.assert_called_once_with("task-789", "summitflow")
    client.update_status.assert_called_once_with("task-789", "completed", skip_gates=True)
    assert result["merged"] is False
    assert result["snapshot_removed"] is True


def test_task_scope_paths_extracts_file_mentions_from_task_text() -> None:
    assert "backend/scripts/persona_honing/__init__.py" in _task_scope_paths(
        {
            "description": "Inspect backend/scripts/persona_honing/__init__.py and fix only if needed.",
        }
    )


def test_complete_task_missing_checkpoint_active_task_auto_commits_dirty_work() -> None:
    client = MagicMock()
    client.get_task.return_value = {
        "status": "pending",
        "project_id": "summitflow",
        "base_branch": "main",
    }
    client.export_task_data.return_value = {
        "task": {"context": {"files_to_modify": ["backend/app/api/heartbeat.py"]}}
    }

    with (
        patch("cli.commands.done_task.get_snapshot_info", return_value=None),
        patch("cli.commands.done_task._reconstruct_snapshot_info", return_value=None),
        patch("cli.commands.done_task._checkpoint_repo_root", return_value="/repo"),
        patch("cli.commands.done_task.is_working_tree_clean", side_effect=[False, True, True]),
        patch("cli.commands.done_task._git_dirty_paths", return_value=["backend/app/api/heartbeat.py"]),
        patch("cli.commands.done_task._task_has_published_commit_event", side_effect=[False, True, True]),
        patch("cli.commands.done_task.commit_repo") as mock_commit,
        patch("app.storage.events.log_task_event") as mock_log,
        patch("cli.commands.done_task.resolve_task_branch", return_value="task/task-789"),
        patch("cli.commands.done_task.check_diff_gate") as mock_diff_gate,
        patch("cli.commands.done_task.merge_task_branch") as mock_merge,
        patch("cli.commands.done_task._publish_completed_work") as mock_publish,
        patch("cli.commands.done_task._run_smart_prereqs") as mock_prereqs,
        patch("cli.commands.done_task.output_success"),
    ):
        mock_commit.return_value = {
            "status": "SUCCESS",
            "commit_id": "abc123",
            "pushed": True,
        }
        mock_diff_gate.return_value = MagicMock(passed=True, summary="ok")
        result = complete_task(client, "task-789", message="finish task")

    mock_commit.assert_called_once()
    assert mock_commit.call_args.kwargs["message"] == "finish task"
    assert mock_commit.call_args.kwargs["task_id"] == "task-789"
    assert mock_commit.call_args.kwargs["push"] is True
    mock_log.assert_called_once()
    assert mock_log.call_args.args[0] == "task-789"
    client.export_task_data.assert_called_once_with("task-789")
    mock_prereqs.assert_called_once_with(
        client, "task-789", "summitflow", merge_subtask_branches=False
    )
    mock_merge.assert_not_called()
    mock_publish.assert_called_once_with("task-789", "summitflow")
    client.update_status.assert_called_once_with("task-789", "completed", skip_gates=True)
    assert result["merged"] is False
    assert result["snapshot_removed"] is True


def test_complete_task_missing_checkpoint_active_task_commits_combined_dirty_checkpoint() -> None:
    client = MagicMock()
    client.get_task.return_value = {
        "status": "pending",
        "project_id": "summitflow",
        "base_branch": "main",
        "context": {"files_to_modify": ["backend/app/api/heartbeat.py"]},
    }
    client.export_task_data.return_value = {}

    with (
        patch("cli.commands.done_task.get_snapshot_info", return_value=None),
        patch("cli.commands.done_task._reconstruct_snapshot_info", return_value=None),
        patch("cli.commands.done_task._checkpoint_repo_root", return_value="/repo"),
        patch("cli.commands.done_task.is_working_tree_clean", side_effect=[False, True, True]),
        patch(
            "cli.commands.done_task._git_dirty_paths",
            return_value=["backend/app/api/heartbeat.py", "frontend/app/database/page.tsx"],
        ),
        patch("cli.commands.done_task._task_has_published_commit_event", side_effect=[False, True]),
        patch("cli.commands.done_task.commit_repo") as mock_commit,
        patch("app.storage.events.log_task_event") as mock_log,
        patch("cli.commands.done_task.resolve_task_branch", return_value="task/task-789"),
        patch("cli.commands.done_task.check_diff_gate") as mock_diff_gate,
        patch("cli.commands.done_task.merge_task_branch") as mock_merge,
        patch("cli.commands.done_task._publish_completed_work") as mock_publish,
        patch("cli.commands.done_task._run_smart_prereqs") as mock_prereqs,
        patch("cli.commands.done_task.output_success"),
    ):
        mock_commit.return_value = {
            "status": "SUCCESS",
            "commit_id": "abc123",
            "pushed": True,
        }
        mock_diff_gate.return_value = MagicMock(passed=True, summary="ok")
        result = complete_task(client, "task-789", message="finish task")

    mock_commit.assert_called_once()
    assert mock_commit.call_args.kwargs["message"] == "finish task"
    assert mock_commit.call_args.kwargs["task_id"] == "task-789"
    assert mock_commit.call_args.kwargs["push"] is True
    mock_log.assert_called_once()
    assert mock_log.call_args.args[0] == "task-789"
    mock_prereqs.assert_called_once_with(
        client, "task-789", "summitflow", merge_subtask_branches=False
    )
    mock_merge.assert_not_called()
    mock_publish.assert_called_once_with("task-789", "summitflow")
    client.update_status.assert_called_once_with("task-789", "completed", skip_gates=True)
    assert result["merged"] is False
    assert result["snapshot_removed"] is True


def test_complete_task_claimed_checkpoint_auto_commits_dirty_branch_before_merge() -> None:
    client = MagicMock()
    client.get_subtasks.return_value = {"subtasks": []}
    client.get_task_completion_readiness.return_value = {"ready": True}
    client.get_task.return_value = {"status": "running"}
    snapshot_info = {
        "task_id": "task-1",
        "project_id": "summitflow",
        "base_branch": "main",
    }

    with (
        patch("cli.commands.done_task.get_snapshot_info", return_value=snapshot_info),
        patch("cli.commands.done_task._checkpoint_repo_root", return_value="/repo"),
        patch("cli.commands.done_task.is_working_tree_clean", side_effect=[False, True, True]),
        patch("cli.commands.done_task.commit_repo") as mock_commit,
        patch("app.storage.events.log_task_event") as mock_log,
        patch("cli.commands.done_task._task_branch_touched_frontend", return_value=False),
        patch("cli.commands.done_task.resolve_task_branch", return_value="task/task-1"),
        patch("cli.commands.done_task.check_diff_gate") as mock_diff_gate,
        patch("cli.commands.done_task.merge_task_branch") as mock_merge,
        patch("cli.commands.done_task._capture_and_remove_snapshot"),
        patch("cli.commands.done_task._publish_completed_work"),
        patch("cli.commands.done_task.output_success"),
    ):
        mock_commit.return_value = {
            "status": "SUCCESS",
            "commit_id": "abc123",
            "pushed": True,
        }
        mock_diff_gate.return_value = MagicMock(passed=True, summary="ok")

        result = complete_task(client, "task-1", message="finish task")

    mock_commit.assert_called_once()
    assert mock_commit.call_args.kwargs["message"] == "finish task"
    assert mock_commit.call_args.kwargs["task_id"] == "task-1"
    assert mock_commit.call_args.kwargs["push"] is True
    mock_log.assert_called_once()
    assert mock_log.call_args.args[0] == "task-1"
    mock_merge.assert_called_once_with("task-1", project_id="summitflow")
    client.update_status.assert_called_once_with("task-1", "completed", skip_gates=False)
    assert result["merged"] is True


def test_run_smart_prereqs_can_pass_subtasks_without_branch_merge() -> None:
    client = MagicMock()
    client.get_subtasks.return_value = {
        "subtasks": [{"subtask_id": "1.1", "passes": False, "citations_status": "acknowledged"}]
    }
    client.get_task_completion_readiness.return_value = {"ready": True}

    with (
        patch("cli.commands.done_task.sync_completed_subtasks") as mock_sync,
        patch("cli.commands.done_subtask.merge_subtask_branch") as mock_merge,
    ):
        mock_sync.return_value.synced = []
        from cli.commands.done_task import _run_smart_prereqs

        _run_smart_prereqs(
            client, "task-789", "summitflow", merge_subtask_branches=False
        )

    client.update_subtask.assert_called_once_with("task-789", "1.1", passes=True)
    mock_merge.assert_not_called()


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

    with (
        patch("cli.commands.done_task.sync_completed_subtasks") as mock_sync,
        patch("cli.commands.done_subtask.merge_subtask_branch"),
    ):
        mock_sync.return_value.synced = []
        from cli.commands.done_task import _run_smart_prereqs

        _run_smart_prereqs(
            client, "task-789", "summitflow", merge_subtask_branches=False
        )

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


def test_complete_task_diff_gate_checks_task_branch_not_current_head() -> None:
    client = MagicMock()
    client.get_subtasks.return_value = {"subtasks": []}
    client.get_task_completion_readiness.return_value = {"ready": True}
    client.get_task.return_value = {"status": "running"}
    snapshot_info = {
        "task_id": "task-1",
        "project_id": "summitflow",
        "base_branch": "main",
    }

    with (
        patch("cli.commands.done_task.get_snapshot_info", return_value=snapshot_info),
        patch("cli.commands.done_task._checkpoint_repo_root", return_value="/repo"),
        patch("cli.commands.done_task.is_working_tree_clean", return_value=True),
        patch("cli.commands.done_task._task_branch_touched_frontend", return_value=False),
        patch("cli.commands.done_task.resolve_task_branch", return_value="task-1/main") as mock_resolve,
        patch("cli.commands.done_task.check_diff_gate") as mock_diff_gate,
        patch("cli.commands.done_task.merge_task_branch"),
        patch("cli.commands.done_task._capture_and_remove_snapshot"),
        patch("cli.commands.done_task._publish_completed_work"),
    ):
        mock_diff_gate.return_value = MagicMock(passed=True, summary="ok")

        complete_task(client, "task-1")

    mock_diff_gate.assert_called_once_with(
        "/repo",
        head_ref="task-1/main",
        base_ref="main",
    )
    mock_resolve.assert_called_once_with("task-1", project_id="summitflow")


def test_complete_task_diff_gate_checks_published_task_bookmark() -> None:
    client = MagicMock()
    client.get_subtasks.return_value = {"subtasks": []}
    client.get_task_completion_readiness.return_value = {"ready": True}
    client.get_task.return_value = {"status": "running"}
    snapshot_info = {
        "task_id": "task-1",
        "project_id": "summitflow",
        "base_branch": "main",
    }

    with (
        patch("cli.commands.done_task.get_snapshot_info", return_value=snapshot_info),
        patch("cli.commands.done_task._checkpoint_repo_root", return_value="/repo"),
        patch("cli.commands.done_task.is_working_tree_clean", return_value=True),
        patch("cli.commands.done_task._task_branch_touched_frontend", return_value=False),
        patch("cli.commands.done_task.resolve_task_branch", return_value="task/task-1") as mock_resolve,
        patch("cli.commands.done_task.check_diff_gate") as mock_diff_gate,
        patch("cli.commands.done_task.merge_task_branch"),
        patch("cli.commands.done_task._capture_and_remove_snapshot"),
        patch("cli.commands.done_task._publish_completed_work"),
    ):
        mock_diff_gate.return_value = MagicMock(passed=True, summary="ok")

        complete_task(client, "task-1")

    mock_diff_gate.assert_called_once_with(
        "/repo",
        head_ref="task/task-1",
        base_ref="main",
    )
    mock_resolve.assert_called_once_with("task-1", project_id="summitflow")


def test_complete_task_normalizes_head_base_branch_before_diff_gate() -> None:
    client = MagicMock()
    client.get_subtasks.return_value = {"subtasks": []}
    client.get_task_completion_readiness.return_value = {"ready": True}
    client.get_task.return_value = {"status": "running"}
    snapshot_info = {
        "task_id": "task-1",
        "project_id": "summitflow",
        "base_branch": "HEAD",
    }

    with (
        patch("cli.commands.done_task.get_snapshot_info", return_value=snapshot_info),
        patch("cli.commands.done_task._checkpoint_repo_root", return_value="/repo"),
        patch("cli.commands.done_task.is_working_tree_clean", return_value=True),
        patch("cli.commands.done_task._task_branch_touched_frontend", return_value=False),
        patch("cli.commands.done_task.resolve_task_branch", return_value="task-1/main"),
        patch("cli.commands.done_task.check_diff_gate") as mock_diff_gate,
        patch("cli.commands.done_task.merge_task_branch"),
        patch("cli.commands.done_task._capture_and_remove_snapshot"),
        patch("cli.commands.done_task._publish_completed_work"),
        patch("cli.commands.done_task.normalize_base_branch", return_value="main") as mock_normalize,
    ):
        mock_diff_gate.return_value = MagicMock(passed=True, summary="ok")

        result = complete_task(client, "task-1")

    mock_normalize.assert_any_call("HEAD", "/repo")
    mock_diff_gate.assert_called_once_with(
        "/repo",
        head_ref="task-1/main",
        base_ref="main",
    )
    assert result["base_branch"] == "main"


def test_resolve_task_branch_prefers_st_commit_bookmark() -> None:
    with (
        patch("cli.lib.checkpoint_branches._get_repo_cwd", return_value="/repo"),
        patch(
            "cli.lib.checkpoint_branches._branch_exists",
            side_effect=lambda branch, _cwd: branch in {"task/task-1", "task-1/main"},
        ),
    ):
        assert resolve_task_branch("task-1", project_id="summitflow") == "task/task-1"
