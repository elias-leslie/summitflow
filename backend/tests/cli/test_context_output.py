"""Tests for compact task context output."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from cli._output_formatters import (
    format_context_snapshot,
    format_context_subtasks,
    format_context_task,
)
from cli.client import APIError
from cli.commands.tasks_context import get_task_context

FRESHNESS_LINE = (
    "FRESHNESS:verify-system-project-state|"
    "task-text=historical|"
    "reshape-or-abandon-if-stale"
)


class TestFormatContextTask:
    """Tests for compact task context formatting."""

    def test_includes_title_and_description_when_present(self) -> None:
        task = {
            "id": "task-123",
            "status": "running",
            "priority": 2,
            "task_type": "bug",
            "complexity": "SIMPLE",
            "title": "Repair ST workflow phase 2",
            "description": "Complete task closure flow follow-through.",
        }

        output = format_context_task(task)

        assert "TASK:task-123|running|P2|bug|SIMPLE" in output
        assert "TITLE:Repair ST workflow phase 2" in output
        assert "DESCRIPTION:Complete task closure flow follow-through." in output

    def test_includes_task_freshness_guardrail_for_active_tasks(self) -> None:
        task = {
            "id": "task-fresh",
            "status": "pending",
            "priority": 2,
            "task_type": "task",
            "complexity": "STANDARD",
            "title": "Review stale task safely",
        }

        output = format_context_task(task)

        assert FRESHNESS_LINE in output

    def test_omits_task_freshness_guardrail_for_final_tasks(self) -> None:
        task = {
            "id": "task-done",
            "status": "completed",
            "priority": 2,
            "task_type": "task",
            "complexity": "STANDARD",
            "title": "Completed task",
        }

        output = format_context_task(task)

        assert "FRESHNESS:" not in output

    def test_omits_empty_workflow_markers(self) -> None:
        task = {
            "id": "task-456",
            "status": "pending",
            "priority": 3,
            "task_type": "task",
            "complexity": "SIMPLE",
            "title": "Validate context output",
            "description": "Keep only useful default fields.",
            "decisions": [],
        }

        output = format_context_task(task)

        assert "WORKFLOW:decisions:0" not in output

    def test_includes_archival_metadata_when_present(self) -> None:
        task = {
            "id": "task-archived",
            "status": "completed",
            "priority": 2,
            "task_type": "task",
            "complexity": "SIMPLE",
            "title": "Recovered audit trail",
            "archived": True,
            "deleted_at": "2026-03-24T00:00:00+00:00",
            "deletion_source": "storage:purge_terminal_tasks",
            "deletion_reason": "Retention purge",
        }

        output = format_context_task(task)

        assert (
            "ARCHIVED:deleted_at:2026-03-24T00:00:00+00:00 | "
            "source:storage:purge_terminal_tasks | reason:Retention purge"
            in output
        )

    def test_runtime_line_surfaces_stuck_after_success_footprint(self) -> None:
        task = {
            "id": "task-94c77a0a",
            "status": "pending",
            "current_phase": "complete",
            "verification_result": {"all_verified": True, "total": 0},
            "priority": 3,
            "task_type": "refactor",
            "complexity": "SIMPLE",
            "title": "Stuck after success",
        }

        output = format_context_task(task)

        assert "RUNTIME:phase=complete | verify=all_verified=true" in output

    def test_runtime_line_silent_when_status_and_phase_aligned(self) -> None:
        task = {
            "id": "task-normal",
            "status": "pending",
            "current_phase": "plan",
            "priority": 3,
            "task_type": "task",
            "complexity": "SIMPLE",
            "title": "Healthy pending task",
        }

        output = format_context_task(task)

        assert "RUNTIME:" not in output

    def test_runtime_line_surfaces_error_message(self) -> None:
        task = {
            "id": "task-failed",
            "status": "failed",
            "current_phase": "execute",
            "error_message": "Diff gate blocked completion: no changes detected",
            "priority": 3,
            "task_type": "task",
            "complexity": "SIMPLE",
            "title": "Failed task",
        }

        output = format_context_task(task)

        assert "phase=execute" in output
        assert "err=Diff gate blocked completion: no changes detected" in output

    def test_includes_lane_overlap_summary_when_present(self) -> None:
        task = {
            "id": "task-789",
            "status": "pending",
            "priority": 2,
            "task_type": "task",
            "complexity": "STANDARD",
            "title": "Coordinate shared plumbing edit",
            "lane_preflight": {
                "issues": ["Another active coding session is already modifying shared plumbing"],
                "disposition": "block",
                "overlap_kind": "shared_plumbing",
                "conflicting_tasks": ["task-999"],
                "owner_location": "checkout /tmp/lanes/task-999",
                "overlap_paths": [
                    "backend/app/services/tools/catalog.py",
                    "backend/app/services/tools/tool_handler.py",
                ],
                "shared_plumbing": True,
            },
        }

        output = format_context_task(task)

        assert (
            "LANE:disp:block | kind:shared_plumbing | tasks:task-999 | owner:checkout /tmp/lanes/task-999 | "
            "paths:backend/app/services/tools/catalog.py,backend/app/services/tools/tool_handler.py | shared:yes"
            in output
        )

    def test_ignores_warn_lane_overlap(self) -> None:
        task = {
            "id": "task-790",
            "status": "pending",
            "priority": 2,
            "task_type": "task",
            "complexity": "STANDARD",
            "title": "Assess adjacent validation lane",
            "lane_preflight": {
                "issues": ["Read-only observer is nonblocking"],
                "disposition": "warn",
                "overlap_kind": "read_observer",
            },
        }

        output = format_context_task(task)

        assert "LANE:" not in output

    def test_includes_active_specialist_summary_when_present(self) -> None:
        task = {
            "id": "task-790",
            "status": "pending",
            "priority": 2,
            "task_type": "task",
            "complexity": "STANDARD",
            "title": "Coordinate specialist follow-through",
            "lane_preflight": {
                "issues": [],
                "active_specialists": [
                    {
                        "agent_slug": "reviewer",
                        "count": 2,
                        "request_sources": ["dispatch"],
                        "newest_age_minutes": 1,
                        "oldest_age_minutes": 4,
                    }
                ],
            },
        }

        output = format_context_task(task)

        assert "SPECIALISTS:reviewer:2:1-4m:dispatch" in output

    def test_includes_completion_readiness_and_sync_hints(self) -> None:
        task = {
            "id": "task-791",
            "status": "running",
            "priority": 2,
            "task_type": "task",
            "complexity": "STANDARD",
            "title": "Finish closure safely",
            "completion_readiness": {
                "ready": False,
                "gates": [{"gate": "subtasks"}, {"gate": "verification"}],
            },
            "syncable_subtasks": ["1.1", "1.2"],
            "syncable_subtasks_skipped": ["1.3:citations", "1.4:steps-2"],
        }

        output = format_context_task(task)

        assert "COMPLETE_READY:no|gates:subtasks,verification" in output
        assert "SYNCABLE_SUBTASKS:1.1,1.2" in output
        assert "SYNC_SKIPS:1.3:citations | 1.4:steps-2" in output

    def test_hides_execution_readiness_noise_for_completed_tasks(self) -> None:
        task = {
            "id": "task-791b",
            "status": "completed",
            "priority": 1,
            "task_type": "feature",
            "complexity": "COMPLEX",
            "title": "Completed high-risk task",
            "plan_status": "draft",
            "execution_readiness": MagicMock(
                ready=False,
                issues=["Missing completed task-shape second opinion"],
                missing_fields=["second_opinion"],
            ),
            "context": {
                "files_to_modify": ["backend/app/api/tasks/workflow.py"],
                "testing_strategy": "Run targeted tests",
                "second_opinion": {
                    "required": True,
                    "stage": "both",
                    "status": "pending",
                },
            },
        }

        output = format_context_task(task)

        assert "WORKFLOW:" not in output
        assert "READINESS:" not in output
        assert "2nd:" not in output
        assert "modify:backend/app/api/tasks/workflow.py" in output

    def test_hides_pending_step_only_sync_skips_without_syncable_subtasks(self) -> None:
        task = {
            "id": "task-792",
            "status": "pending",
            "priority": 2,
            "task_type": "task",
            "complexity": "STANDARD",
            "title": "Pending validation task",
            "syncable_subtasks": [],
            "syncable_subtasks_skipped": ["1.1:steps-1,2", "1.2:steps-1,2"],
        }

        output = format_context_task(task)

        assert "SYNC_SKIPS:" not in output

    def test_keeps_pending_non_step_sync_skips_visible(self) -> None:
        task = {
            "id": "task-793",
            "status": "pending",
            "priority": 2,
            "task_type": "task",
            "complexity": "STANDARD",
            "title": "Pending citation follow-up",
            "syncable_subtasks": [],
            "syncable_subtasks_skipped": ["1.3:citations", "1.4:steps-2"],
        }

        output = format_context_task(task)

        assert "SYNC_SKIPS:1.3:citations" in output
        assert "1.4:steps-2" not in output

    def test_omits_lane_preflight_for_terminal_tasks_without_injecting_noise(self) -> None:
        task = {
            "id": "task-794",
            "status": "cancelled",
            "priority": 2,
            "task_type": "task",
            "complexity": "STANDARD",
            "title": "Cancelled validation task",
        }

        output = format_context_task(task)

        assert "LANE:" not in output

    def test_includes_harness_route_and_execution_contract_summary(self) -> None:
        task = {
            "id": "task-795",
            "status": "pending",
            "priority": 2,
            "task_type": "feature",
            "complexity": "STANDARD",
            "title": "Critique dashboard design",
            "context": {
                "execution_contract": {
                    "mode": "runtime_eval_plus_design",
                    "target_urls": ["/app/dashboard"],
                    "user_flows": [{"title": "Open dashboard"}],
                    "api_checks": [{"method": "GET", "path": "/dashboard"}],
                    "negative_cases": [{"title": "Missing dashboard"}],
                    "design_criteria": {"rubric": ["craft", "usability"]},
                }
            },
            "harness_route": {
                "mode": "runtime_eval_plus_design",
                "reasons": ["frontend_scope", "design_criteria"],
            },
        }

        output = format_context_task(task)

        assert "HARNESS:runtime_eval_plus_design|reasons:frontend_scope,design_criteria" in output
        assert "CONTRACT:urls=1|flows=1|api=1|negative=1|design=yes" in output

    def test_includes_fixed_continuity_sections_when_present(self) -> None:
        task = {
            "id": "task-796",
            "status": "pending",
            "priority": 2,
            "task_type": "task",
            "complexity": "STANDARD",
            "title": "Resume context repair",
            "continuity": {
                "objective": "Make resume reliable",
                "current_slice": "2.1 Render continuity block",
                "blockers": ["task-9|pending|Blocked by review"],
                "recent_progress": ["[2026-04-12 10:05:00] Wired logs"],
                "next_action": "2.1.1 Wire logs",
                "key_files": ["backend/cli/commands/tasks_context.py"],
            },
        }

        output = format_context_task(task)

        assert "OBJECTIVE:Make resume reliable" in output
        assert "CURRENT_SLICE:2.1 Render continuity block" in output
        assert "BLOCKERS[1]" in output
        assert "RECENT_PROGRESS[1]" in output
        assert "NEXT_ACTION:2.1.1 Wire logs" in output
        assert "KEY_FILES[1]:backend/cli/commands/tasks_context.py" in output



class TestFormatContextSnapshot:
    """Tests for snapshot/checkpoint state formatting."""

    def test_formats_active_snapshot_with_core_fields(self) -> None:
        snapshot = {
            "claimed_by": "agent-coder",
            "created_at": "2026-03-10T14:30:00.123456",
            "base_branch": "main",
            "branch": "task/task-123",
        }

        output = format_context_snapshot(snapshot)

        assert "SNAPSHOT:active|claimed_by:agent-coder|since:2026-03-10T14:30:00" in output
        assert "BASE_BRANCH:main" in output
        assert "TASK_BRANCH:task/task-123" in output

    def test_returns_empty_for_empty_snapshot(self) -> None:
        assert format_context_snapshot({}) == ""

    def test_returns_empty_for_no_snapshot(self) -> None:
        # Simulates a task with no active checkpoint
        output = format_context_snapshot({})
        assert output == ""

    def test_partial_snapshot_without_branch(self) -> None:
        snapshot = {
            "claimed_by": "human",
            "created_at": "2026-03-10T10:00:00",
            "base_branch": "main",
        }

        output = format_context_snapshot(snapshot)

        assert "SNAPSHOT:active|claimed_by:human|since:2026-03-10T10:00:00" in output
        assert "TASK_BRANCH" not in output
        assert "PORTS" not in output


class TestFormatContextSubtasks:
    """Tests for compact subtask context formatting."""

    def test_omits_empty_subtasks_marker(self) -> None:
        output = format_context_subtasks([])

        assert output == ""


class TestTaskContextCommand:
    def test_get_task_context_skips_lane_preflight_for_cancelled_task(self) -> None:
        client = MagicMock()
        client.get_task.return_value = {
            "id": "task-1",
            "project_id": "summitflow",
            "status": "cancelled",
            "task_type": "task",
            "priority": 2,
            "complexity": "STANDARD",
            "title": "Cancelled validation task",
        }
        client.get_subtasks.return_value = {"subtasks": []}
        client.list_dependencies.return_value = []
        client.get_task_completion_readiness.return_value = {"ready": False, "gates": []}

        with (
            patch("cli.commands.tasks_context._enrich_task_from_spirit"),
            patch("cli.commands.tasks_context.assess_task_execution_readiness", return_value={}),
            patch("cli.commands.tasks_context.fetch_triggered_references", return_value=[]),
            patch("cli.commands.tasks_context.analyze_subtask_sync") as mock_sync,
            patch("cli.commands.tasks_context.output_context"),
            patch("cli.commands.tasks_context.check_task_lane_conflicts") as mock_lane,
            patch("cli.commands.tasks_context._load_snapshot_info", return_value=None),
        ):
            mock_sync.return_value.syncable = []
            mock_sync.return_value.skipped = []
            get_task_context("task-1", None, client)

        mock_lane.assert_not_called()

    def test_get_task_context_skips_execution_readiness_for_completed_task(self) -> None:
        client = MagicMock()
        client.get_task.return_value = {
            "id": "task-2",
            "project_id": "summitflow",
            "status": "completed",
            "task_type": "feature",
            "priority": 1,
            "complexity": "COMPLEX",
            "title": "Completed redesign task",
        }
        client.get_subtasks.return_value = {"subtasks": []}
        client.list_dependencies.return_value = []
        client.get_task_completion_readiness.return_value = {"ready": True, "gates": []}

        with (
            patch("cli.commands.tasks_context._enrich_task_from_spirit"),
            patch("cli.commands.tasks_context.assess_task_execution_readiness") as mock_readiness,
            patch("cli.commands.tasks_context.fetch_triggered_references", return_value=[]),
            patch("cli.commands.tasks_context.analyze_subtask_sync") as mock_sync,
            patch("cli.commands.tasks_context.output_context"),
            patch("cli.commands.tasks_context.check_task_lane_conflicts") as mock_lane,
            patch("cli.commands.tasks_context._load_snapshot_info", return_value=None),
        ):
            mock_sync.return_value.syncable = []
            mock_sync.return_value.skipped = []
            get_task_context("task-2", None, client)

        mock_readiness.assert_not_called()
        mock_lane.assert_not_called()

    def test_get_task_context_builds_continuity_from_summary_and_logs(self) -> None:
        client = MagicMock()
        client.get_task.return_value = {
            "id": "task-3",
            "project_id": "summitflow",
            "status": "pending",
            "task_type": "task",
            "priority": 2,
            "complexity": "STANDARD",
            "title": "Continuity repair",
            "objective": "Make resume reliable",
            "context": {"files_to_modify": ["backend/cli/commands/tasks_context.py"]},
        }
        client.get_subtasks.return_value = {
            "subtasks": [
                {
                    "subtask_id": "2.1",
                    "description": "Render continuity block",
                    "display_order": 2,
                    "passes": False,
                    "steps": [{"step_number": 1, "description": "Wire logs", "passes": False}],
                }
            ],
            "summary": {"next_subtask_id": "2.1"},
        }
        client.get_task_logs.return_value = {
            "entries": ["[2026-04-12 10:05:00] Wired logs"],
            "count": 1,
        }
        client.list_dependencies.return_value = []
        client.get_task_completion_readiness.return_value = {"ready": False, "gates": []}

        with (
            patch("cli.commands.tasks_context._enrich_task_from_spirit"),
            patch("cli.commands.tasks_context.assess_task_execution_readiness", return_value={}),
            patch("cli.commands.tasks_context.fetch_triggered_references", return_value=[]),
            patch("cli.commands.tasks_context.analyze_subtask_sync") as mock_sync,
            patch("cli.commands.tasks_context.output_context") as mock_output,
            patch("cli.commands.tasks_context.check_task_lane_conflicts") as mock_lane,
            patch("cli.commands.tasks_context._load_snapshot_info", return_value=None),
        ):
            mock_sync.return_value.syncable = []
            mock_sync.return_value.skipped = []
            mock_lane.return_value.to_dict.return_value = {
                "issues": [],
                "suggestions": [],
                "conflicting_tasks": [],
                "overlap_kind": None,
                "overlap_paths": [],
                "shared_plumbing": False,
                "disposition": "allow",
                "owner_session_id": None,
                "owner_branch": None,
                "owner_location": None,
                "active_specialists": [],
            }
            get_task_context("task-3", None, client)

        output_task = mock_output.call_args.args[0]
        assert output_task["continuity"] == {
            "objective": "Make resume reliable",
            "current_slice": "2.1 Render continuity block",
            "blockers": [],
            "recent_progress": ["[2026-04-12 10:05:00] Wired logs"],
            "next_action": "2.1.1 Wire logs",
            "key_files": ["backend/cli/commands/tasks_context.py"],
        }

    def test_get_task_context_falls_back_to_archived_snapshot(self) -> None:
        client = MagicMock()
        client.get_task.side_effect = APIError(404, "Task task-1 not found")
        archived = {
            "task": {
                "id": "task-1",
                "project_id": "summitflow",
                "status": "completed",
                "task_type": "task",
                "priority": 2,
                "complexity": "STANDARD",
                "title": "Archived monkey-fight task",
            },
            "subtasks": [{"subtask_id": "1.1", "description": "Preserved subtask"}],
            "deleted_at": "2026-03-24T00:00:00+00:00",
            "deletion_source": "storage:purge_terminal_tasks",
            "deletion_reason": "Retention purge",
        }

        with (
            patch(
                "cli.commands.tasks_context.task_store.get_deleted_task_context",
                return_value=archived,
            ),
            patch("cli.commands.tasks_context.output_context") as mock_output,
        ):
            get_task_context("task-1", None, client)

        archived_task = mock_output.call_args.args[0]
        assert archived_task["archived"] is True
        assert archived_task["deletion_source"] == "storage:purge_terminal_tasks"
        assert archived_task["deletion_reason"] == "Retention purge"
        assert mock_output.call_args.args[1] == archived["subtasks"]
