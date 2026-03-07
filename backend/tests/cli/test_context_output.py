"""Tests for compact task context output."""

from __future__ import annotations

from cli._output_formatters import format_context_subtasks, format_context_task


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



class TestFormatContextSubtasks:
    """Tests for compact subtask context formatting."""

    def test_omits_empty_subtasks_marker(self) -> None:
        output = format_context_subtasks([])

        assert output == ""
