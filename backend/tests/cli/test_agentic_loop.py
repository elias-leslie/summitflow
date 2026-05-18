"""End-to-end coverage of the canonical agentic loop.

These tests pin the friction-removal guarantees from
plan `the-way-tasks-are-eager-parnas`:

  * `st create <title>` accepts a bare title and auto-enriches (no --plan ritual).
  * `st create --plan plan.json` imports a pre-validated plan.
  * `st claim` is idempotent for the same caller.
  * `st done` on an already-completed task is a no-op exit-0.
  * Exactly one preflight call per claim/done op (no double-gate matrix).
  * Publish runs *before* checkpoint removal; a publish failure leaves the
    snapshot intact and surfaces a retry hint.
  * Every blocked preflight path prints a Resolution: hint.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from cli.commands import claim, done, done_subtask, done_task
from cli.commands.tasks import app as tasks_app
from cli.commands.tasks_create import _build_task_data

runner = CliRunner()


def _running_task(task_id: str = "task-1", project_id: str = "summitflow") -> dict[str, object]:
    return {
        "id": task_id,
        "status": "running",
        "project_id": project_id,
        "execution_mode": "autonomous",
        "plan_status": "approved",
        "claimed_by": "tester",
    }


# ---------------------------------------------------------------------------
# §2 create: bare title → auto-enrichment; --draft skips it
# ---------------------------------------------------------------------------


class TestCreateSurface:
    def test_bare_title_marks_for_auto_enrichment(self) -> None:
        mock_client = MagicMock()
        mock_client.create_task.return_value = {"id": "task-mock"}
        with patch("cli.commands.tasks_create.STClient", return_value=mock_client):
            result = runner.invoke(tasks_app, ["create", "fix login redirect bug"])
        assert result.exit_code == 0
        payload = mock_client.create_task.call_args.args[0]
        assert payload["auto_dispatch"] is True
        assert payload["title"] == "fix login redirect bug"

    def test_draft_skips_auto_enrichment(self) -> None:
        data = _build_task_data(
            title="Stash this", task_type="task", priority=2,
            description=None, labels=None, parent=None,
            execution_mode=None, manual_only=False, autonomous=False, draft=True,
        )
        assert "auto_dispatch" not in data

    def test_plan_import_path_does_not_demand_p_flag(self) -> None:
        with (
            patch("cli.commands.tasks_create.STClient"),
            patch(
                "cli.commands.tasks_create.import_plan_file",
                return_value=({"complexity": "SIMPLE", "subtasks": []}, "task-mock"),
            ),
        ):
            result = runner.invoke(tasks_app, ["create", "--plan", "plan.json"])
        assert result.exit_code == 0
        assert "IMPORT:task-mock|SIMPLE|intent-only" in result.output


# ---------------------------------------------------------------------------
# §4 + §5 single preflight + idempotency
# ---------------------------------------------------------------------------


class TestClaimIdempotency:
    def test_same_caller_resume_returns_resumed_no_preflight(self) -> None:
        """Idempotent re-claim by the same worker is a `resumed` no-op."""
        client = MagicMock()
        client.get_task.return_value = _running_task()
        with (
            patch.object(claim, "get_snapshot_info", return_value={"base_branch": "main"}),
            patch.object(claim, "_is_same_caller", return_value=True),
            patch.object(claim, "preflight") as mock_preflight,
        ):
            result = claim._claim_task(client, "task-1")
        assert result["action"] == "resumed"
        # Same-caller resume is the idempotent shortcut — no gates fire.
        mock_preflight.assert_not_called()

    def test_cross_agent_conflict_emits_resolution_hint(self) -> None:
        """Cross-agent re-claim blocks with a Resolution line."""
        client = MagicMock()
        task = _running_task()
        task["claimed_by"] = "other-agent"
        client.get_task.return_value = task

        with (
            patch.object(claim, "get_snapshot_info", return_value={"base_branch": "main"}),
            patch.object(claim, "_is_same_caller", return_value=False),
            patch.object(claim, "output_error") as mock_error,
            pytest.raises(typer.Exit),
        ):
            claim._claim_task(client, "task-1")
        msg = mock_error.call_args.args[0]
        assert "already claimed" in msg
        assert "Resolution" in msg


class TestSinglePreflight:
    def test_claim_runs_preflight_exactly_once(self) -> None:
        client = MagicMock()
        client.get_task.return_value = {
            "id": "task-1",
            "status": "pending",
            "project_id": "summitflow",
            "execution_mode": "manual",
            "plan_status": "approved",
        }
        with (
            patch.object(claim, "get_snapshot_info", return_value=None),
            patch.object(claim, "preflight") as mock_preflight,
            patch.object(claim, "create_task_snapshot") as mock_snapshot,
        ):
            mock_snapshot.return_value = MagicMock(base_branch="main")
            claim._claim_task(client, "task-1")
        mock_preflight.assert_called_once_with("task-1", "summitflow", op="claim")

    def test_done_runs_preflight_exactly_once(self) -> None:
        client = MagicMock()
        client.get_task.return_value = {
            "id": "task-1",
            "status": "running",
            "project_id": "summitflow",
        }
        with (
            patch.object(done, "STClient"),
            patch.object(done, "preflight") as mock_preflight,
            patch.object(
                done, "complete_task",
                return_value={"project_id": "summitflow", "merged": False},
            ),
        ):
            done._handle_task_completion(client, "task-1", "done")
        mock_preflight.assert_called_once_with("task-1", "summitflow", op="done")


# ---------------------------------------------------------------------------
# §5 done idempotency
# ---------------------------------------------------------------------------


class TestDoneIdempotency:
    def test_already_completed_task_is_noop_exit_zero(self, capsys) -> None:
        client = MagicMock()
        client.get_task.return_value = {
            "id": "task-1",
            "status": "completed",
            "project_id": "summitflow",
        }
        with (
            patch.object(done, "preflight") as mock_preflight,
            patch.object(done, "complete_task") as mock_complete,
            patch.object(done, "output_success") as mock_success,
        ):
            done._handle_task_completion(client, "task-1", None)
        mock_complete.assert_not_called()
        mock_preflight.assert_not_called()
        msg = mock_success.call_args.args[0]
        assert "already complete" in msg

    def test_already_passed_subtask_is_noop(self) -> None:
        client = MagicMock()
        client.get_subtasks.return_value = {
            "subtasks": [{"subtask_id": "1.1", "passes": True}]
        }
        result = done_subtask.complete_subtask(client, "1.1", "task-1")
        assert result == {
            "task_id": "task-1",
            "subtask_id": "1.1",
            "action": "noop",
            "merged": False,
        }
        client.update_subtask.assert_not_called()


# ---------------------------------------------------------------------------
# §7 publish-before-cleanup ordering
# ---------------------------------------------------------------------------


class TestPublishBeforeCleanup:
    def test_publish_runs_before_snapshot_remove(self) -> None:
        order: list[str] = []
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
            patch.object(done_task, "get_snapshot_info", return_value=snapshot_info),
            patch.object(done_task, "_checkpoint_repo_root", return_value="/repo"),
            patch.object(done_task, "is_working_tree_clean", return_value=True),
            patch.object(done_task, "_task_branch_touched_frontend", return_value=False),
            patch.object(done_task, "_run_diff_gate"),
            patch.object(done_task, "_run_smart_prereqs"),
            patch.object(done_task, "merge_task_branch"),
            patch.object(done_task, "_finalize_completed_task_status", return_value=False),
            patch.object(
                done_task, "_publish_completed_work",
                side_effect=lambda *_a, **_kw: order.append("publish"),
            ),
            patch.object(
                done_task, "_capture_and_remove_snapshot",
                side_effect=lambda *_a, **_kw: order.append("snapshot-remove"),
            ),
        ):
            done_task.complete_task(client, "task-1")
        assert order == ["publish", "snapshot-remove"]

    def test_publish_failure_preserves_snapshot_and_surfaces_retry(self) -> None:
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
            patch.object(done_task, "get_snapshot_info", return_value=snapshot_info),
            patch.object(done_task, "_checkpoint_repo_root", return_value="/repo"),
            patch.object(done_task, "is_working_tree_clean", return_value=True),
            patch.object(done_task, "_task_branch_touched_frontend", return_value=False),
            patch.object(done_task, "_run_diff_gate"),
            patch.object(done_task, "_run_smart_prereqs"),
            patch.object(done_task, "merge_task_branch"),
            patch.object(done_task, "_finalize_completed_task_status", return_value=False),
            patch.object(
                done_task, "_publish_completed_work",
                side_effect=RuntimeError("network glitch"),
            ),
            patch.object(done_task, "_capture_and_remove_snapshot") as mock_cleanup,
            patch.object(done_task, "output_warning") as mock_warn,
            pytest.raises(typer.Exit),
        ):
            done_task.complete_task(client, "task-1")

        mock_cleanup.assert_not_called()
        msg = mock_warn.call_args.args[0]
        assert "Publish failed" in msg
        assert "Resolution" in msg
        assert "st done task-1" in msg


# ---------------------------------------------------------------------------
# §8 resolution hints on every blocked path
# ---------------------------------------------------------------------------


class TestResolutionHints:
    def test_pulse_gate_block_includes_resolution(self) -> None:
        """A blocked pulse gate prints a Resolution line for the typed reason."""
        from cli.commands.pulse import require_pulse_gate

        payload = {
            "summary": {"active_owners": 0, "active_specialists": 0, "active_sessions": 0},
            "cleanup": {"active_checkpoints": 0},
        }
        with (
            patch("cli.commands.pulse.fetch_pulse_payload", return_value=payload),
            patch(
                "cli.commands.pulse.preflight_reasons_for_payload",
                return_value=["jj_conflicts"],
            ),
            patch("cli.commands.pulse.output_error") as mock_error,
            pytest.raises(typer.Exit),
        ):
            require_pulse_gate("summitflow")
        msg = mock_error.call_args.args[0]
        assert "Pulse gate blocked" in msg
        assert "Resolution" in msg
        assert "st vcs reconcile" in msg

    def test_rejected_plan_blocks_with_resolution(self) -> None:
        """`st claim` on a plan_status=rejected task blocks with a hint."""
        from cli.commands.claim import _enforce_plan_status_gate

        task = {"id": "task-1", "plan_status": "rejected", "execution_mode": "autonomous"}
        with patch("cli.commands.claim.output_error") as mock_error, pytest.raises(typer.Exit):
            _enforce_plan_status_gate(task)
        msg = mock_error.call_args.args[0]
        assert "rejected" in msg
        assert "Resolution" in msg
        assert "st update task-1 --plan" in msg


# ---------------------------------------------------------------------------
# §6 docs/config auto-skip
# ---------------------------------------------------------------------------


class TestDocsConfigAutoSkip:
    def test_docs_only_diff_skips_gate(self) -> None:
        with patch("cli.commands.done_task.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="docs/foo.md\nbackend/README.md\n",
            )
            assert done_task._is_diff_docs_or_config_only("/repo", "task-1/main", "main") is True

    def test_code_diff_is_not_docs_only(self) -> None:
        with patch("cli.commands.done_task.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="backend/cli/main.py\n",
            )
            assert done_task._is_diff_docs_or_config_only("/repo", "task-1/main", "main") is False


# ---------------------------------------------------------------------------
# §10 schema sweep: autonomous derived, not stored
# ---------------------------------------------------------------------------


class TestSchemaSweep:
    def test_autonomous_column_dropped_from_select(self) -> None:
        from app.storage.tasks.columns import EXPECTED_TASK_COLUMNS, TASK_COLUMNS

        assert EXPECTED_TASK_COLUMNS == 39
        normalized = " ".join(TASK_COLUMNS.split())
        # `autonomous` (boolean column) must not be in the SELECT list.
        # The substring `autonomous` could legitimately appear as a tail
        # match — assert the surrounding-comma form to be precise.
        assert ", autonomous," not in normalized
        assert "execution_mode" in normalized
