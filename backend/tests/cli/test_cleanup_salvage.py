"""Tests for cleanup salvage helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import typer

from cli.commands import cleanup_salvage
from cli.commands.cleanup_salvage import coerce_created_at, recover_orphan_task


def test_coerce_created_at_accepts_datetime_for_checkpoint_metadata() -> None:
    created_at = datetime(2026, 4, 24, 9, 8, tzinfo=UTC)

    assert coerce_created_at(created_at) == "2026-04-24T09:08:00+00:00"


def test_recover_orphan_task_saves_datetime_as_string(mocker) -> None:
    repo_path = Path("/tmp/summitflow")
    task_id = "task-abc12345"
    item = SimpleNamespace(branch_name=f"{task_id}/main", has_node_modules_artifact=False)
    created_at = datetime(2026, 4, 24, 9, 8, tzinfo=UTC)
    git_result = SimpleNamespace(returncode=0, stdout="task-current/main\n", stderr="")

    mocker.patch.object(cleanup_salvage, "get_branch_subject", return_value="Recover branch")
    mocker.patch.object(cleanup_salvage.task_store, "create_task", return_value={"id": task_id, "created_at": created_at})
    mocker.patch.object(cleanup_salvage.task_store, "update_task")
    mocker.patch.object(cleanup_salvage, "run_git", return_value=git_result)
    mocker.patch.object(cleanup_salvage, "get_claimed_by", return_value="tester")
    mock_save = mocker.patch.object(cleanup_salvage, "save_snapshot_meta")

    recover_orphan_task(repo_path, item, task_id)

    meta = mock_save.call_args.args[0]
    assert meta.created_at == "2026-04-24T09:08:00+00:00"


def test_recover_orphan_task_restores_original_branch_on_failure(mocker) -> None:
    repo_path = Path("/tmp/summitflow")
    task_id = "task-abc12345"
    branch_name = f"{task_id}/main"
    item = SimpleNamespace(branch_name=branch_name, has_node_modules_artifact=False)
    current_result = SimpleNamespace(returncode=0, stdout="task-current/main\n", stderr="")
    checkout_result = SimpleNamespace(returncode=0, stdout="", stderr="")

    mocker.patch.object(cleanup_salvage, "get_branch_subject", return_value="Recover branch")
    mocker.patch.object(cleanup_salvage.task_store, "create_task", return_value={"id": task_id, "created_at": None})
    mocker.patch.object(cleanup_salvage.task_store, "update_task")
    mock_delete = mocker.patch.object(cleanup_salvage.task_store, "delete_task")
    mock_run_git = mocker.patch.object(cleanup_salvage, "run_git", side_effect=[current_result, checkout_result, checkout_result])
    mocker.patch.object(cleanup_salvage, "save_snapshot_meta", side_effect=TypeError("not json safe"))

    with pytest.raises(typer.Exit):
        recover_orphan_task(repo_path, item, task_id)

    assert mock_run_git.call_args_list[1].args[0] == ["checkout", branch_name]
    assert mock_run_git.call_args_list[2].args[0] == ["checkout", "task-current/main"]
    mock_delete.assert_called_once_with(task_id, deletion_source="cli:cleanup.salvage_rollback")
