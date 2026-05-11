"""Regression tests for autonomous follow-up task reuse."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from app.services.task_execution_readiness import load_task_execution_readiness
from app.storage import tasks as task_store
from app.storage.connection import get_connection
from app.storage.subtasks import create_subtask, get_subtasks_for_task
from app.storage.task_spirit import get_task_spirit, upsert_task_spirit
from app.tasks.autonomous.exec_modules.completion_handler import handle_partial_completion
from app.tasks.autonomous.exec_modules.followup_tasks import (
    _build_followup_description,
    _build_followup_title,
    _normalize_failed_subtask_ids,
    create_followup_task_for_failures,
)


@pytest.fixture
def cleanup_tasks(db_schema_initialized: None, ensure_test_project: str) -> Iterator[list[str]]:
    """Track and cleanup test tasks after tests."""
    task_ids: list[str] = []
    yield task_ids
    if task_ids:
        with get_connection() as conn, conn.cursor() as cur:
            for task_id in reversed(task_ids):
                cur.execute(
                    "DELETE FROM task_subtask_steps WHERE subtask_id IN (SELECT id FROM task_subtasks WHERE task_id = %s)",
                    (task_id,),
                )
                cur.execute("DELETE FROM task_subtasks WHERE task_id = %s", (task_id,))
                cur.execute("DELETE FROM task_spirit WHERE task_id = %s", (task_id,))
                cur.execute("DELETE FROM task_labels WHERE task_id = %s", (task_id,))
                cur.execute(
                    "DELETE FROM task_dependencies WHERE task_id = %s OR depends_on_task_id = %s",
                    (task_id, task_id),
                )
                cur.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
            conn.commit()


class TestNormalizeFailedSubtaskIds:
    def test_sorts_dedupes_and_trims_usable_subtask_ids(self) -> None:
        failed_results = [
            {"subtask_id": " 2.0 "},
            {"subtask_id": "1.0"},
            {"subtask_id": "2.0"},
            {"subtask_id": ""},
            {"subtask_id": "   "},
            {"subtask_id": None},
            {},
            {"subtask_id": 123},
        ]

        assert _normalize_failed_subtask_ids(failed_results) == ["1.0", "2.0"]

    def test_description_uses_sentinel_when_no_usable_subtask_ids(self) -> None:
        description = _build_followup_description(
            "task-123",
            [{"subtask_id": "  "}, {"subtask_id": None}, {}],
        )

        assert "- __no_subtask_ids__" in description


class TestCreateFollowupTaskForFailures:
    def test_new_followup_inherits_runnable_package_and_syncs_ready(
        self,
        test_project_id: str,
        cleanup_tasks: list[str],
    ) -> None:
        parent = task_store.create_task(
            project_id=test_project_id,
            title="Parent task",
            description="Parent task description",
            task_type="task",
            priority=2,
        )
        cleanup_tasks.append(parent["id"])

        upsert_task_spirit(
            parent["id"],
            done_when=["Persist planner context on follow-up retry"],
            context={
                "objective": "Finish the unresolved planner-path work",
                "files_to_modify": ["backend/app/api/tasks/update_endpoints.py"],
                "testing_strategy": "Run focused API tests",
            },
            complexity="STANDARD",
        )
        create_subtask(
            parent["id"],
            "1.1",
            "Persist planner context",
            display_order=0,
            phase="backend",
            steps=["Reproduce the failure", "Patch the update path"],
        )
        create_subtask(
            parent["id"],
            "1.2",
            "Run focused backend validation",
            display_order=1,
            phase="backend",
            depends_on=["1.1"],
            steps=[{"description": "Run dt pytest backend/tests/api/test_task_workflow.py"}],
        )

        followup_id = create_followup_task_for_failures(
            parent["id"],
            test_project_id,
            [{"subtask_id": "1.2", "error": "readiness key missing in context payload"}],
        )

        assert followup_id is not None
        cleanup_tasks.append(followup_id)

        followup = task_store.get_task(followup_id)
        spirit = get_task_spirit(followup_id)
        subtasks = get_subtasks_for_task(followup_id, include_steps=True)
        readiness = load_task_execution_readiness(followup_id)

        assert followup is not None
        assert spirit is not None
        assert "1.2: readiness key missing in context payload" in str(followup["description"])
        assert followup["parent_task_id"] == parent["id"]
        assert followup["labels"] == ["autocode-followup"]
        assert spirit["done_when"] == [
            f"Resolve unresolved work carried from {parent['id']}",
            "1.2 Run focused backend validation",
            "Focused validation passes for the follow-up changes",
        ]
        assert spirit["plan_status"] == "approved"
        assert spirit["context"]["source_task_id"] == parent["id"]
        assert spirit["context"]["failed_subtask_ids"] == ["1.2"]
        assert spirit["context"]["parent_done_when"] == ["Persist planner context on follow-up retry"]
        assert spirit["context"]["failure_summaries"] == {
            "1.2": "readiness key missing in context payload",
        }
        assert spirit["context"]["files_to_modify"] == ["backend/app/api/tasks/update_endpoints.py"]
        assert spirit["context"]["subtasks"] == [
            {
                "subtask_id": "1.2",
                "description": "Run focused backend validation",
                "phase": "backend",
                "steps": [
                    {
                        "step_number": 1,
                        "description": "Run dt pytest backend/tests/api/test_task_workflow.py",
                        "passes": False,
                    }
                ],
            }
        ]
        assert [subtask["subtask_id"] for subtask in subtasks] == ["1.2"]
        assert subtasks[0]["depends_on"] == []
        assert subtasks[0]["steps"] == [
            {
                "step_number": 1,
                "description": "Run dt pytest backend/tests/api/test_task_workflow.py",
                "passes": False,
            }
        ]
        assert readiness.ready is True

    def test_repeated_same_input_reuses_existing_pending_followup_and_refreshes_description(
        self,
        test_project_id: str,
        cleanup_tasks: list[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        parent = task_store.create_task(
            project_id=test_project_id,
            title="Parent task",
            description="parent",
            task_type="task",
        )
        cleanup_tasks.append(parent["id"])

        info_logs: list[str] = []
        monkeypatch.setattr(
            "app.tasks.autonomous.exec_modules.followup_tasks.emit_log",
            lambda task_id, level, message, **kwargs: info_logs.append(message)
            if level == "info" and task_id == parent["id"]
            else None,
        )

        first_id = create_followup_task_for_failures(
            parent["id"],
            test_project_id,
            [{"subtask_id": "2.0"}, {"subtask_id": "1.0"}],
        )
        assert first_id is not None
        cleanup_tasks.append(first_id)

        second_id = create_followup_task_for_failures(
            parent["id"],
            test_project_id,
            [{"subtask_id": " 3.0 "}, {"subtask_id": "2.0"}, {"subtask_id": "3.0"}],
        )

        assert second_id == first_id

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, title, parent_task_id, status, description, priority
                FROM tasks
                WHERE project_id = %s AND parent_task_id = %s
                ORDER BY created_at ASC, id ASC
                """,
                (test_project_id, parent["id"]),
            )
            followups = cur.fetchall()

        assert len(followups) == 1
        followup_id, title, parent_task_id, status, description, priority = followups[0]
        assert followup_id == first_id
        assert title == _build_followup_title(parent["id"])
        assert parent_task_id == parent["id"]
        assert status == "pending"
        assert priority == 1
        assert description == _build_followup_description(
            parent["id"],
            [{"subtask_id": " 3.0 "}, {"subtask_id": "2.0"}, {"subtask_id": "3.0"}],
        )
        assert any("Created follow-up task" in message for message in info_logs)
        assert any("Reused follow-up task" in message for message in info_logs)

    def test_reuses_oldest_pending_match_when_duplicates_already_exist(
        self,
        test_project_id: str,
        cleanup_tasks: list[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        parent = task_store.create_task(
            project_id=test_project_id,
            title="Parent task",
            description="parent",
            task_type="task",
        )
        cleanup_tasks.append(parent["id"])

        title = _build_followup_title(parent["id"])
        older = task_store.create_task(
            project_id=test_project_id,
            title=title,
            description="old desc",
            task_type="task",
            parent_task_id=parent["id"],
            priority=1,
            autonomous=True,
        )
        newer = task_store.create_task(
            project_id=test_project_id,
            title=title,
            description="new desc",
            task_type="task",
            parent_task_id=parent["id"],
            priority=1,
            autonomous=True,
        )
        cleanup_tasks.extend([older["id"], newer["id"]])

        logs: list[str] = []
        monkeypatch.setattr(
            "app.tasks.autonomous.exec_modules.followup_tasks.emit_log",
            lambda task_id, level, message, **kwargs: logs.append(message)
            if level == "info" and task_id == parent["id"]
            else None,
        )

        reused_id = create_followup_task_for_failures(
            parent["id"],
            test_project_id,
            [{"subtask_id": "z"}, {"subtask_id": "a"}],
        )

        assert reused_id == older["id"]
        older_after = task_store.get_task(older["id"])
        newer_after = task_store.get_task(newer["id"])
        assert older_after is not None
        assert newer_after is not None
        assert older_after["description"] == _build_followup_description(
            parent["id"],
            [{"subtask_id": "z"}, {"subtask_id": "a"}],
        )
        assert newer_after["description"] == "new desc"
        assert older_after["status"] == "pending"
        assert newer_after["status"] == "pending"
        assert older_after["title"] == title
        assert newer_after["title"] == title
        assert older_after["parent_task_id"] == parent["id"]
        assert newer_after["parent_task_id"] == parent["id"]
        assert any(f"Reused follow-up task {older['id']}" in message for message in logs)

    def test_tie_breaker_uses_lowest_task_id_when_created_at_matches(
        self,
        test_project_id: str,
        cleanup_tasks: list[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        parent = task_store.create_task(
            project_id=test_project_id,
            title="Parent task",
            description="parent",
            task_type="task",
        )
        cleanup_tasks.append(parent["id"])

        title = _build_followup_title(parent["id"])
        first = task_store.create_task(
            project_id=test_project_id,
            title=title,
            description="first desc",
            task_type="task",
            parent_task_id=parent["id"],
            priority=1,
            autonomous=True,
        )
        second = task_store.create_task(
            project_id=test_project_id,
            title=title,
            description="second desc",
            task_type="task",
            parent_task_id=parent["id"],
            priority=1,
            autonomous=True,
        )
        cleanup_tasks.extend([first["id"], second["id"]])

        chosen_id = min(first["id"], second["id"])
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET created_at = NOW() WHERE id IN (%s, %s)",
                (first["id"], second["id"]),
            )
            conn.commit()

        logs: list[str] = []
        monkeypatch.setattr(
            "app.tasks.autonomous.exec_modules.followup_tasks.emit_log",
            lambda task_id, level, message, **kwargs: logs.append(message)
            if level == "info" and task_id == parent["id"]
            else None,
        )

        reused_id = create_followup_task_for_failures(
            parent["id"],
            test_project_id,
            [{"subtask_id": "9.9"}],
        )

        assert reused_id == chosen_id
        assert any(f"Reused follow-up task {chosen_id}" in message for message in logs)

    def test_completed_or_failed_matches_do_not_block_new_followup(
        self,
        test_project_id: str,
        cleanup_tasks: list[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        parent = task_store.create_task(
            project_id=test_project_id,
            title="Parent task",
            description="parent",
            task_type="task",
        )
        cleanup_tasks.append(parent["id"])

        title = _build_followup_title(parent["id"])
        done_followup = task_store.create_task(
            project_id=test_project_id,
            title=title,
            description="done",
            task_type="task",
            parent_task_id=parent["id"],
            priority=1,
            autonomous=True,
        )
        failed_followup = task_store.create_task(
            project_id=test_project_id,
            title=title,
            description="failed",
            task_type="task",
            parent_task_id=parent["id"],
            priority=1,
            autonomous=True,
        )
        cleanup_tasks.extend([done_followup["id"], failed_followup["id"]])
        task_store.update_task_status(done_followup["id"], "running")
        task_store.update_task_status(done_followup["id"], "running")
        task_store.update_task_status(done_followup["id"], "completed")
        task_store.update_task_status(failed_followup["id"], "running")
        task_store.update_task_status(failed_followup["id"], "running")
        task_store.update_task_status(failed_followup["id"], "failed")

        logs: list[str] = []
        monkeypatch.setattr(
            "app.tasks.autonomous.exec_modules.followup_tasks.emit_log",
            lambda task_id, level, message, **kwargs: logs.append(message)
            if level == "info" and task_id == parent["id"]
            else None,
        )

        new_id = create_followup_task_for_failures(
            parent["id"], test_project_id, [{"subtask_id": "1.2"}]
        )

        assert new_id not in {done_followup["id"], failed_followup["id"]}
        cleanup_tasks.append(new_id)
        new_followup = task_store.get_task(new_id)
        assert new_followup is not None
        assert new_followup["status"] == "pending"
        assert new_followup["title"] == title
        assert new_followup["parent_task_id"] == parent["id"]
        assert any(f"Created follow-up task {new_id}" in message for message in logs)

    def test_cross_parent_pending_match_is_ignored(
        self,
        test_project_id: str,
        cleanup_tasks: list[str],
    ) -> None:
        first_parent = task_store.create_task(
            project_id=test_project_id,
            title="Parent one",
            description="parent",
            task_type="task",
        )
        second_parent = task_store.create_task(
            project_id=test_project_id,
            title="Parent two",
            description="parent",
            task_type="task",
        )
        cleanup_tasks.extend([first_parent["id"], second_parent["id"]])

        first_followup_id = create_followup_task_for_failures(
            first_parent["id"], test_project_id, [{"subtask_id": "1.1"}]
        )
        assert first_followup_id is not None
        cleanup_tasks.append(first_followup_id)

        second_followup_id = create_followup_task_for_failures(
            second_parent["id"], test_project_id, [{"subtask_id": "1.1"}]
        )
        assert second_followup_id is not None
        cleanup_tasks.append(second_followup_id)

        assert second_followup_id != first_followup_id
        second_followup = task_store.get_task(second_followup_id)
        assert second_followup is not None
        assert second_followup["parent_task_id"] == second_parent["id"]

    @pytest.mark.parametrize("bad_parent_id", [None, "", "   ", "missing-parent", "task-missing-parent"])
    def test_invalid_parent_id_skips_creation_and_emits_warn(
        self,
        bad_parent_id: str | None,
        test_project_id: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        logs: list[tuple[str, str, str]] = []
        monkeypatch.setattr(
            "app.tasks.autonomous.exec_modules.followup_tasks.emit_log",
            lambda task_id, level, message, **kwargs: logs.append((task_id, level, message)),
        )

        def followup_count() -> int:
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM tasks WHERE project_id = %s AND title LIKE %s",
                    (test_project_id, "Follow-up: stuck subtasks from %"),
                )
                row = cur.fetchone()
                assert row is not None
                return int(row[0])

        before_count = followup_count()

        result = create_followup_task_for_failures(
            bad_parent_id,
            test_project_id,
            [{"subtask_id": "1.1"}],
        )

        assert result is None
        assert logs == [
            (
                bad_parent_id if isinstance(bad_parent_id, str) else "",
                "warn",
                "Skipped follow-up task creation: invalid parent task id",
            )
        ]

        assert followup_count() == before_count

    def test_reuse_only_updates_description_field(
        self,
        test_project_id: str,
        cleanup_tasks: list[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        parent = task_store.create_task(
            project_id=test_project_id,
            title="Parent task",
            description="parent",
            task_type="task",
        )
        cleanup_tasks.append(parent["id"])

        followup_id = create_followup_task_for_failures(
            parent["id"],
            test_project_id,
            [{"subtask_id": "1.0"}],
        )
        assert followup_id is not None
        cleanup_tasks.append(followup_id)

        import app.tasks.autonomous.exec_modules.followup_tasks as followup_module

        updates: list[tuple[str, dict[str, object]]] = []
        real_update = followup_module.update_task_fields

        def tracking_update(task_id: str, **fields: object) -> None:
            updates.append((task_id, fields))
            real_update(task_id, **fields)

        monkeypatch.setattr(followup_module, "update_task_fields", tracking_update)

        reused_id = create_followup_task_for_failures(
            parent["id"],
            test_project_id,
            [{"subtask_id": "2.0"}],
        )

        assert reused_id == followup_id
        assert updates == [
            (
                followup_id,
                {"description": _build_followup_description(parent["id"], [{"subtask_id": "2.0"}])},
            )
        ]

    def test_race_overlap_recheck_reuses_oldest_pending_after_competing_create(
        self,
        test_project_id: str,
        cleanup_tasks: list[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        parent = task_store.create_task(
            project_id=test_project_id,
            title="Parent task",
            description="parent",
            task_type="task",
        )
        cleanup_tasks.append(parent["id"])

        import app.tasks.autonomous.exec_modules.followup_tasks as followup_module

        real_find = followup_module._find_pending_followup_task
        real_create = followup_module.create_task
        call_count = {"find": 0}

        def fake_find(parent_task_id: str, project_id: str, title: str):
            call_count["find"] += 1
            return real_find(parent_task_id, project_id, title)

        def fake_create_task(**kwargs):
            if call_count["find"] == 1:
                competing = real_create(**kwargs)
                cleanup_tasks.append(competing["id"])
            return real_create(**kwargs)

        monkeypatch.setattr(followup_module, "_find_pending_followup_task", fake_find)
        monkeypatch.setattr(followup_module, "create_task", fake_create_task)

        followup_id = create_followup_task_for_failures(
            parent["id"], test_project_id, [{"subtask_id": "1.4"}]
        )

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM tasks WHERE project_id = %s AND parent_task_id = %s ORDER BY created_at ASC, id ASC",
                (test_project_id, parent["id"]),
            )
            rows = cur.fetchall()

        ids = [row[0] for row in rows]
        cleanup_tasks.extend(task_id for task_id in ids if task_id not in cleanup_tasks)
        assert len(ids) == 2
        assert followup_id == ids[0]
        assert ids[0] != ids[1]


class TestHandlePartialCompletionFollowupWiring:
    def test_repeated_partial_completion_reuses_existing_followup(
        self,
        test_project_id: str,
        cleanup_tasks: list[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        parent = task_store.create_task(
            project_id=test_project_id,
            title="Multi-step feature",
            description="parent",
            task_type="feature",
        )
        cleanup_tasks.append(parent["id"])
        task_store.update_task_status(parent["id"], "running")

        info_logs: list[str] = []
        monkeypatch.setattr(
            "app.tasks.autonomous.exec_modules.followup_tasks.emit_log",
            lambda task_id, level, message, **kwargs: info_logs.append(message)
            if level == "info" and task_id == parent["id"]
            else None,
        )

        dispatch = MagicMock()
        first_results = [
            {"subtask_id": "1.1", "status": "passed"},
            {"subtask_id": " 2.2 ", "status": "failed"},
        ]
        second_results = [
            {"subtask_id": "1.1", "status": "passed"},
            {"subtask_id": "3.3", "status": "failed"},
            {"subtask_id": "2.2", "status": "failed"},
            {"subtask_id": "3.3", "status": "failed"},
            {"subtask_id": None, "status": "failed"},
        ]

        assert handle_partial_completion(parent["id"], test_project_id, "/tmp/test", first_results, dispatch)
        assert handle_partial_completion(parent["id"], test_project_id, "/tmp/test", second_results, dispatch)

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, description, title, parent_task_id, status
                FROM tasks
                WHERE project_id = %s AND parent_task_id = %s
                ORDER BY created_at ASC, id ASC
                """,
                (test_project_id, parent["id"]),
            )
            rows = cur.fetchall()

        assert len(rows) == 1
        followup_id, description, title, parent_task_id, status = rows[0]
        cleanup_tasks.append(followup_id)
        assert title == _build_followup_title(parent["id"])
        assert parent_task_id == parent["id"]
        assert status == "pending"
        assert description == _build_followup_description(
            parent["id"],
            [result for result in second_results if result.get("status") != "passed"],
        )
        assert any("Created follow-up task" in message for message in info_logs)
        assert any(f"Reused follow-up task {followup_id}" in message for message in info_logs)
