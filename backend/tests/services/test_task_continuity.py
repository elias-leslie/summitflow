"""Unit tests for task continuity contract helpers."""

from __future__ import annotations

from app.services.task_continuity import build_continuity, format_continuity_lines


class TestBuildContinuity:
    def test_builds_continuity_from_existing_task_data(self) -> None:
        continuity = build_continuity(
            task={"id": "task-1", "objective": "Ship safely"},
            spirit={"context": {"files_to_modify": ["a.py", "b.py"], "files_to_create": ["b.py", "c.py"]}},
            subtasks=[
                {
                    "subtask_id": "1.1",
                    "description": "Done slice",
                    "display_order": 2,
                    "passes": True,
                },
                {
                    "subtask_id": "2.1",
                    "description": "Render continuity block",
                    "display_order": 3,
                    "passes": False,
                    "depends_on": ["1.1", "9.9"],
                    "steps": [
                        {"step_number": 1, "description": "Wire logs", "passes": False},
                        {"step_number": 2, "description": "Render next action", "passes": False},
                    ],
                },
            ],
            blockers=[
                {"id": "task-9", "status": "pending", "title": "Blocked by review"},
                {"id": "task-3", "status": "running", "title": "Blocked by migration"},
                {"id": "task-7", "status": "pending", "title": "Blocked by auth"},
                {"id": "task-8", "status": "pending", "title": "Overflow blocker"},
            ],
            progress_log=[
                "  [2026-04-12 10:00:00] Started audit  ",
                "[2026-04-12 10:05:00] Wired logs",
                "[2026-04-12 10:05:00] Wired logs",
                "",
                "[2026-04-12 10:10:00] Rendered context",
            ],
            summary={"next_subtask_id": "2.1"},
        )

        assert continuity == {
            "objective": "Ship safely",
            "current_slice": "2.1 Render continuity block",
            "blockers": [
                "task-3|running|Blocked by migration",
                "task-7|pending|Blocked by auth",
                "task-8|pending|Overflow blocker",
                "+1 more omitted",
            ],
            "recent_progress": [
                "[2026-04-12 10:00:00] Started audit",
                "[2026-04-12 10:05:00] Wired logs",
                "[2026-04-12 10:10:00] Rendered context",
            ],
            "next_action": "2.1.1 Wire logs",
            "key_files": ["a.py", "b.py", "c.py"],
        }

    def test_falls_back_to_absence_values(self) -> None:
        continuity = build_continuity(
            task={"id": "task-2"},
            spirit={"context": {}},
            subtasks=[],
            blockers=[],
            progress_log=[],
            summary={},
        )

        assert continuity == {
            "objective": "none recorded",
            "current_slice": "none inferred",
            "blockers": [],
            "recent_progress": [],
            "next_action": "none inferred",
            "key_files": [],
        }


class TestFormatContinuityLines:
    def test_formats_fixed_section_order_and_absence_text(self) -> None:
        lines = format_continuity_lines(
            {
                "objective": "none recorded",
                "current_slice": "none inferred",
                "blockers": [],
                "recent_progress": [],
                "next_action": "none inferred",
                "key_files": [],
            }
        )

        assert lines == [
            "OBJECTIVE:none recorded",
            "CURRENT_SLICE:none inferred",
            "BLOCKERS:none explicit",
            "RECENT_PROGRESS:none recorded",
            "NEXT_ACTION:none inferred",
            "KEY_FILES:none recorded",
        ]
