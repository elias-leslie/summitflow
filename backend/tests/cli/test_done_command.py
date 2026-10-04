from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from cli.commands.done import _handle_task_completion, _refuse_if_autocode_owned, app

runner = CliRunner()


def test_refuse_when_task_is_claimed_by_autocode_dispatcher() -> None:
    task: dict[str, object] = {
        "id": "task-94c77a0a",
        "claimed_by": "api-dispatch-agent-hub",
        "lock_expires_at": "2026-05-11T16:34:11Z",
    }
    with (
        patch("cli.commands.done.output_error") as mock_error,
        pytest.raises(typer.Exit),
    ):
        _refuse_if_autocode_owned(task, "task-94c77a0a")
    assert mock_error.called
    msg = mock_error.call_args[0][0]
    assert "api-dispatch-agent-hub" in msg
    assert "dispatcher owns completion" in msg


def test_allow_when_claim_is_empty() -> None:
    _refuse_if_autocode_owned({"id": "task-x"}, "task-x")
    _refuse_if_autocode_owned({"id": "task-x", "claimed_by": None}, "task-x")
    _refuse_if_autocode_owned({"id": "task-x", "claimed_by": ""}, "task-x")


def test_allow_when_task_is_claimed_by_non_dispatch_worker() -> None:
    _refuse_if_autocode_owned({"id": "task-x", "claimed_by": "davion-sidarli"}, "task-x")
    _refuse_if_autocode_owned({"id": "task-x", "claimed_by": "worker-1"}, "task-x")


def test_already_completed_task_is_noop() -> None:
    """Idempotent close: `st done` on an already-completed task returns 0."""
    lookup_client = MagicMock()
    lookup_client.get_task.return_value = {
        "id": "task-1",
        "status": "completed",
        "project_id": "portfolio-ai",
    }
    with (
        patch("cli.commands.done.get_snapshot_info", return_value=None),
        patch("cli.commands.done.STClient") as client_cls,
        patch("cli.commands.done.preflight") as mock_gate,
        patch("cli.commands.done.complete_task") as mock_complete,
        patch("cli.commands.done.output_success") as mock_success,
    ):
        _handle_task_completion(lookup_client, "task-1", "done")

    mock_success.assert_called_once()
    assert "already complete" in mock_success.call_args[0][0]
    mock_complete.assert_not_called()
    mock_gate.assert_not_called()
    client_cls.assert_not_called()


def test_completed_task_with_checkpoint_retries_closeout() -> None:
    lookup_client = MagicMock()
    lookup_client.get_task.return_value = {
        "id": "task-1",
        "status": "completed",
        "project_id": "portfolio-ai",
    }
    project_client = MagicMock()

    with (
        patch("cli.commands.done.get_snapshot_info", return_value={"task_id": "task-1"}),
        patch("cli.commands.done.STClient", return_value=project_client),
        patch("cli.commands.done.preflight") as mock_gate,
        patch(
            "cli.commands.done.complete_task",
            return_value={"snapshot_removed": True, "base_branch": "main"},
        ) as mock_complete,
        patch("cli.commands.done.output_success"),
    ):
        _handle_task_completion(lookup_client, "task-1", "retry publish")

    mock_gate.assert_called_once_with("task-1", "portfolio-ai", op="done")
    mock_complete.assert_called_once_with(project_client, "task-1", "retry publish")


def test_task_completion_uses_task_project_client_after_global_lookup() -> None:
    lookup_client = MagicMock()
    lookup_client.get_task.return_value = {
        "id": "task-1",
        "status": "running",
        "project_id": "portfolio-ai",
    }
    project_client = MagicMock()

    with (
        patch("cli.commands.done.STClient", return_value=project_client) as client_cls,
        patch("cli.commands.done.preflight") as mock_gate,
        patch(
            "cli.commands.done.complete_task",
            return_value={"merged": False, "project_id": "portfolio-ai"},
        ) as mock_complete,
        patch("cli.commands.done.output_success"),
    ):
        _handle_task_completion(lookup_client, "task-1", "done")

    lookup_client.get_task.assert_called_once_with("task-1")
    client_cls.assert_called_once_with(project_id="portfolio-ai")
    mock_complete.assert_called_once_with(project_client, "task-1", "done")
    mock_gate.assert_called_once_with("task-1", "portfolio-ai", op="done")


def test_done_dotted_id_uses_subtask_completion_path() -> None:
    with (
        patch("cli.commands.done.STClient") as mock_client_cls,
        patch("cli.commands.done.complete_subtask") as mock_complete_subtask,
        patch("cli.commands.done.complete_task") as mock_complete_task,
        patch("cli.commands.done.output_success"),
    ):
        mock_complete_subtask.return_value = {"action": "completed"}
        result = runner.invoke(app, ["1.1", "--task", "task-parent"])

    assert result.exit_code == 0
    mock_client_cls.assert_called_once_with()
    mock_complete_subtask.assert_called_once_with(
        mock_client_cls.return_value,
        "1.1",
        "task-parent",
        None,
        citations=None,
        acknowledge_none=False,
    )
    mock_complete_task.assert_not_called()


def test_completed_task_without_checkpoint_resumes_incomplete_local_cleanup():
    from cli.commands import done
    client = MagicMock()
    client.get_task.return_value = {"status": "completed", "project_id": "example", "verification_result": {
        "closeout": {"kind": "local_closeout.v1", "state": "blocked"}}}
    with (
        patch.object(done, "get_snapshot_info", return_value=None),
        patch.object(done, "preflight"),
        patch.object(done, "STClient", return_value=client),
        patch.object(done, "complete_task", return_value={"action": "completed"}) as complete,
        patch.object(done, "_release_task_leases"),
    ):
        done._handle_task_completion(client, "task-local", None)
    complete.assert_called_once_with(client, "task-local", None)


@pytest.mark.parametrize("status,basis", [("running", "validated"), ("completed", "retained")])
def test_quiet_completion_shows_selected_source_and_evidence_without_extra_reads(status, basis, capsys):
    from app.services.task_closeout import completion_evidence
    from cli.commands import done

    receipt = {"state": "success", "source_commit": "a" * 40,
               "acceptance_id": "proof-id", "acceptance_artifact": "/repo/.git/st/acceptance/proof-id.json"}
    client = MagicMock()
    client.get_task.return_value = {"status": status, "project_id": "example",
                                    "verification_result": {"acceptance": receipt}}
    selected = {"action": "completed", "snapshot_removed": True, "base_branch": "main",
                **completion_evidence(receipt)}
    with (
        patch.object(done, "get_snapshot_info", return_value=None) as snapshot,
        patch.object(done, "preflight") as gate,
        patch.object(done, "STClient", return_value=client) as client_factory,
        patch.object(done, "complete_task", return_value=selected) as complete,
        patch.object(done, "_release_task_leases"),
        patch("cli.lib.acceptance.accept_revision", side_effect=AssertionError("No evidence discovery")),
        patch("cli.lib.acceptance.validate_acceptance_receipt", side_effect=AssertionError("No extra validation")),
    ):
        done._handle_task_completion(client, "task-local", None)
    output = capsys.readouterr().out
    assert ("already complete (no-op)" if status == "completed" else "completed. Checkpoint removed.") in output
    assert f"Source: {'a' * 40} ({basis} acceptance)" in output
    assert "Evidence: proof-id; /repo/.git/st/acceptance/proof-id.json" in output
    assert "Blockers: none" in output
    assert "Next action: none" in output
    client.get_task.assert_called_once_with("task-local")
    if status == "completed":
        snapshot.assert_called_once_with("task-local")
        complete.assert_not_called()
        gate.assert_not_called()
        client_factory.assert_not_called()
    else:
        snapshot.assert_not_called()
        complete.assert_called_once_with(client, "task-local", None)
        gate.assert_called_once_with("task-local", "example", op="done")


def test_record_only_completion_does_not_manufacture_source_or_proof(capsys):
    from app.services.task_closeout import completion_evidence
    from cli.commands import done

    client = MagicMock()
    client.get_task.return_value = {"status": "running", "project_id": "example"}
    with (
        patch.object(done, "STClient", return_value=client),
        patch.object(done, "preflight"),
        patch.object(done, "complete_task", return_value={"action": "completed",
            **completion_evidence({}, record_only=True)}) as complete,
        patch.object(done, "_release_task_leases"),
    ):
        done._handle_task_completion(client, "task-admin", None, record_only=True)
    output = capsys.readouterr().out
    assert "Source: not_applicable (record-only)" in output
    assert "Evidence: not_applicable (record-only)" in output
    assert "Blockers: none" in output
    assert "Next action: none" in output
    assert "validated" not in output
    complete.assert_called_once_with(client, "task-admin", None, admin=True)


@pytest.mark.parametrize("action", ["pending", "blocked", "skipped"])
def test_unfinished_closeout_never_prints_complete_summary(action, capsys):
    from cli.commands import done

    client = MagicMock()
    client.get_task.return_value = {"status": "running", "project_id": "example"}
    with (
        patch.object(done, "STClient", return_value=client),
        patch.object(done, "preflight"),
        patch.object(done, "complete_task", return_value={"action": action, "reason": "source changed"}),
        patch.object(done, "_release_task_leases") as release,
    ):
        if action == "pending":
            done._handle_task_completion(client, "task-local", None)
        else:
            with pytest.raises(typer.Exit):
                done._handle_task_completion(client, "task-local", None)
    output = capsys.readouterr().out
    assert "Blockers: none" not in output
    assert "Next action: none" not in output
    assert "validated acceptance" not in output
    release.assert_not_called()


def test_failed_task_cli_refuses_before_completion_or_cleanup():
    from cli.commands import done

    client = MagicMock()
    client.get_task.return_value = {"status": "failed", "project_id": "example", "verification_result": {
        "acceptance": {"state": "failed", "source_commit": "a" * 40}}}
    with (
        patch.object(done, "STClient", return_value=client),
        patch.object(done, "get_snapshot_info") as snapshot,
        patch.object(done, "preflight") as gate,
        patch.object(done, "complete_task", return_value={"action": "completed"}) as complete,
        patch.object(done, "_release_task_leases") as release,
    ):
        result = runner.invoke(app, ["task-failed"])
    assert result.exit_code == 1
    assert "is failed" in result.output
    assert "st reopen task-failed" in result.output and "st claim task-failed" in result.output
    assert "completed" not in result.output
    assert "Blockers: none" not in result.output
    assert "Next action: none" not in result.output
    complete.assert_not_called()
    release.assert_not_called()
    gate.assert_not_called()
    snapshot.assert_not_called()
    client.get_task.assert_called_once_with("task-failed")
