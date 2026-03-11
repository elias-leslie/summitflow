"""Tests for compact task context output."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from cli._output_formatters import (
    format_context_snapshot,
    format_context_subtasks,
    format_context_task,
)
from cli.commands.tasks_context import get_task_context


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

    def test_includes_lane_overlap_summary_when_present(self) -> None:
        task = {
            "id": "task-789",
            "status": "pending",
            "priority": 2,
            "task_type": "task",
            "complexity": "STANDARD",
            "title": "Coordinate shared plumbing edit",
            "lane_preflight": {
                "issues": ["Another active coding lane is already modifying shared plumbing"],
                "disposition": "block",
                "overlap_kind": "shared_plumbing",
                "conflicting_tasks": ["task-999"],
                "owner_location": "worktree /tmp/worktrees/task-999",
                "overlap_paths": [
                    "backend/app/services/tools/catalog.py",
                    "backend/app/services/tools/tool_handler.py",
                ],
                "shared_plumbing": True,
            },
        }

        output = format_context_task(task)

        assert (
            "LANE:disp:block | kind:shared_plumbing | tasks:task-999 | owner:worktree /tmp/worktrees/task-999 | "
            "paths:backend/app/services/tools/catalog.py,backend/app/services/tools/tool_handler.py | shared:yes"
            in output
        )

    def test_formats_warn_lane_as_advisory_overlap(self) -> None:
        task = {
            "id": "task-790",
            "status": "pending",
            "priority": 2,
            "task_type": "task",
            "complexity": "STANDARD",
            "title": "Assess adjacent validation lane",
            "lane_preflight": {
                "issues": ["Another active coding lane exists in project summitflow but lacks usable file scope"],
                "disposition": "warn",
                "overlap_kind": "unscoped_target",
                "conflicting_tasks": ["task-42f6700b"],
                "owner_location": "worktree /tmp/worktrees/task-42f6700b",
            },
        }

        output = format_context_task(task)

        assert (
            "LANE_ADVISORY:disp:warn | kind:unscoped_target | active_tasks:task-42f6700b | "
            "owner:worktree /tmp/worktrees/task-42f6700b"
            in output
        )

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



class TestFormatContextSnapshot:
    """Tests for snapshot/checkpoint state formatting."""

    def test_formats_active_snapshot_with_all_fields(self) -> None:
        snapshot = {
            "claimed_by": "agent-coder",
            "created_at": "2026-03-10T14:30:00.123456",
            "base_branch": "main",
            "worktree_path": "/home/user/.local/share/st/worktrees/proj/task-123",
            "worktree_branch": "task/task-123",
            "backend_port": 8081,
            "frontend_port": 3001,
        }

        output = format_context_snapshot(snapshot)

        assert "SNAPSHOT:active|claimed_by:agent-coder|since:2026-03-10T14:30:00" in output
        assert "BASE_BRANCH:main" in output
        assert "WORKTREE_PATH:/home/user/.local/share/st/worktrees/proj/task-123" in output
        assert "TASK_BRANCH:task/task-123" in output
        assert "PORTS:backend:8081 | frontend:3001" in output

    def test_returns_empty_for_empty_snapshot(self) -> None:
        assert format_context_snapshot({}) == ""

    def test_returns_empty_for_no_snapshot(self) -> None:
        # Simulates a task with no active checkpoint
        output = format_context_snapshot({})
        assert output == ""

    def test_partial_snapshot_without_worktree(self) -> None:
        snapshot = {
            "claimed_by": "human",
            "created_at": "2026-03-10T10:00:00",
            "base_branch": "main",
        }

        output = format_context_snapshot(snapshot)

        assert "SNAPSHOT:active|claimed_by:human|since:2026-03-10T10:00:00" in output
        assert "WORKTREE_PATH" not in output
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
            patch("cli.commands.tasks_context.get_worktree_info", return_value=None),
        ):
            mock_sync.return_value.syncable = []
            mock_sync.return_value.skipped = []
            get_task_context("task-1", None, client)

        mock_lane.assert_not_called()
