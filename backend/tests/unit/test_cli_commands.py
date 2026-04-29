"""Tests for CLI commands.

Tests the st CLI commands including batch creation from file.

IMPORTANT: All tests use mocked storage/client to avoid hitting production DB.
This file tests CLI behavior with mocked backends - it does NOT create real tasks.
"""

from __future__ import annotations

import json
import tarfile
import tempfile
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import ANY, MagicMock, patch

import jsonschema
import pytest
from typer.testing import CliRunner

from cli.commands.subtask import app as subtask_app
from cli.commands.tasks import app as tasks_app
from cli.commands.tasks_import import import_plan_file

runner = CliRunner()


def _make_mock_task(task_id: str, **kwargs: Any) -> dict[str, Any]:
    """Create a mock task dict with default values."""
    return {
        "id": task_id,
        "project_id": kwargs.get("project_id", "summitflow"),
        "capability_id": None,
        "title": kwargs.get("title", "Mock Task"),
        "description": kwargs.get("description"),
        "status": kwargs.get("status", "pending"),
        "progress_log": [],
        "error_message": None,
        "branch_name": None,
        "commits": [],
        "total_sessions": 0,
        "total_tokens_used": 0,
        "created_at": datetime.now(UTC).isoformat(),
        "started_at": None,
        "completed_at": None,
        "priority": kwargs.get("priority", 2),
        "task_type": kwargs.get("task_type", "task"),
        "parent_task_id": None,
        "feature_id": None,
        "claimed_by": None,
        "claimed_at": None,
        "lock_expires_at": None,
        "tier": None,
        "pre_merge_sha": None,
        "review_result": None,
        "current_phase": "plan",
        "verification_result": None,
        "raw_request": None,
        "enrichment_status": "none",
        "enriched_by": None,
        "enriched_at": None,
        "complexity": kwargs.get("complexity"),
        "execution_mode": kwargs.get("execution_mode", "manual"),
        "autonomous": kwargs.get("execution_mode") == "autonomous" or kwargs.get("autonomous", False),
        # Spirit fields
        "objective": None,
        "spirit_anti": None,
        "decisions": [],
        "constraints": [],
        "done_when": [],
        "plan_status": None,
    }


def _make_mock_subtask(task_id: str, subtask_id: str, **kwargs: Any) -> dict[str, Any]:
    """Create a mock subtask dict with default values."""
    return {
        "id": 1,
        "task_id": task_id,
        "subtask_id": subtask_id,
        "description": kwargs.get("description", "Mock Subtask"),
        "phase": kwargs.get("phase", "implementation"),
        "status": "pending",
        "display_order": kwargs.get("display_order", 0),
        "steps": kwargs.get("steps", []),
        "created_at": datetime.now(UTC).isoformat(),
        "started_at": None,
        "completed_at": None,
    }


@pytest.fixture
def mock_st_client() -> Generator[tuple[MagicMock, dict[str, dict[str, Any]]]]:
    """Mock STClient to avoid real HTTP calls to API.

    This fixture mocks the CLI's HTTP client so no real API calls are made.
    Used for tests that invoke CLI commands which would otherwise hit the real API.
    """
    task_counter = [0]
    tasks_db: dict[str, dict[str, Any]] = {}

    def mock_create_task(data: dict[str, Any]) -> dict[str, Any]:
        task_counter[0] += 1
        task_id = f"task-mock-{task_counter[0]:08x}"
        task = _make_mock_task(task_id, **data)
        tasks_db[task_id] = task
        return task

    def mock_batch_create_tasks(items: list[dict[str, Any]]) -> dict[str, Any]:
        created = []
        for item in items:
            task = mock_create_task(item)
            created.append(task)
        return {"created": created, "errors": []}

    def mock_get_task(task_id: str) -> dict[str, Any]:
        task = tasks_db.get(task_id)
        if not task:
            from cli.client import APIError

            raise APIError(404, f"Task {task_id} not found")
        return task

    # Create mock client instance
    mock_client = MagicMock()
    mock_client.create_task = mock_create_task
    mock_client.batch_create_tasks = mock_batch_create_tasks
    mock_client.get_task = mock_get_task
    mock_client.project_id = "test-project"

    # Mock the STClient class to return our mock instance
    # Patch both the direct reference and the import in tasks_import
    with (
        patch("cli.commands.tasks.STClient", return_value=mock_client),
        patch("cli.commands.tasks_import.STClient", return_value=mock_client),
    ):
        yield mock_client, tasks_db


@pytest.fixture
def mock_storage() -> Generator[dict[str, Any]]:
    """Mock storage layer to avoid hitting production DB.

    This fixture mocks the storage modules for tests that directly
    call storage functions (not through CLI/API).
    """
    task_counter = [0]
    subtask_counter = [0]
    tasks_db: dict[str, Any] = {}
    subtasks_db: dict[str, Any] = {}  # key: f"{task_id}:{subtask_id}"

    def mock_create_task(project_id: str, title: str, **kwargs: Any) -> dict[str, Any]:
        task_counter[0] += 1
        task_id = kwargs.get("task_id") or f"task-mock-{task_counter[0]:08x}"
        task = _make_mock_task(task_id, project_id=project_id, title=title, **kwargs)
        tasks_db[task_id] = task
        return task

    def mock_get_task(task_id: str) -> dict[str, Any] | None:
        return tasks_db.get(task_id)

    def mock_delete_task(task_id: str) -> bool:
        if task_id in tasks_db:
            del tasks_db[task_id]
            return True
        return False

    def mock_create_subtask(task_id: str, subtask_id: str, description: str, **kwargs: Any) -> dict[str, Any]:
        subtask_counter[0] += 1
        key = f"{task_id}:{subtask_id}"
        subtask = _make_mock_subtask(task_id, subtask_id, description=description, **kwargs)
        subtasks_db[key] = subtask
        return subtask

    def mock_get_subtask(task_id: str, subtask_id: str) -> dict[str, Any] | None:
        key = f"{task_id}:{subtask_id}"
        return subtasks_db.get(key)

    def mock_list_subtasks(task_id: str) -> list[dict[str, Any]]:
        return [s for s in subtasks_db.values() if s["task_id"] == task_id]

    with (
        patch("app.storage.tasks.create_task", side_effect=mock_create_task),
        patch("app.storage.tasks.get_task", side_effect=mock_get_task),
        patch("app.storage.tasks.delete_task", side_effect=mock_delete_task),
        patch("app.storage.subtasks.create_subtask", side_effect=mock_create_subtask),
        patch("app.storage.subtasks.get_subtask", side_effect=mock_get_subtask),
        patch("app.storage.subtasks.list_subtasks", side_effect=mock_list_subtasks),
    ):
        yield {"tasks": tasks_db, "subtasks": subtasks_db}


class TestCreateFromFile:
    """Test st create --from-file functionality.

    These tests verify the CLI correctly parses JSON files and creates tasks.
    Uses mock_st_client to avoid hitting the real API.
    """

    @pytest.fixture(autouse=True)
    def _bypass_project_check(self) -> Generator[None]:
        """Bypass require_explicit_project since tests invoke tasks_app directly."""
        with patch("cli.commands.tasks_import.require_explicit_project"):
            yield

    def test_from_file_valid_json(self, mock_st_client: tuple[MagicMock, dict[str, dict[str, Any]]]) -> None:
        """Test creating tasks from a valid JSON file."""
        tasks_data = {
            "tasks": [
                {
                    "title": "CLI Test Task 1",
                    "task_type": "task",
                    "priority": 3,
                    "labels": ["complexity:small"],
                },
                {
                    "title": "CLI Test Task 2",
                    "task_type": "feature",
                    "priority": 2,
                },
            ]
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(tasks_data, f)
            f.flush()

            result = runner.invoke(tasks_app, ["create", "--from-file", f.name])

            # Should succeed
            assert result.exit_code == 0
            assert "Created: 2/2 tasks" in result.output

            # Verify tasks were created in mock
            _, tasks_db = mock_st_client
            assert len(tasks_db) == 2

    def test_from_file_with_subtasks(self, mock_st_client: tuple[MagicMock, dict[str, dict[str, Any]]]) -> None:
        """Test creating a full task with subtasks and steps."""
        tasks_data = {
            "tasks": [
                {
                    "title": "CLI Full Task Test",
                    "task_type": "feature",
                    "priority": 2,
                    "subtasks": [
                        {
                            "subtask_id": "1.1",
                            "phase": "backend",
                            "description": "Test subtask",
                            "steps": ["Step 1", "Step 2", "Step 3"],
                        }
                    ],
                }
            ]
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(tasks_data, f)
            f.flush()

            result = runner.invoke(tasks_app, ["create", "--from-file", f.name])

            assert result.exit_code == 0
            assert "Created: 1/1 tasks" in result.output

    def test_from_file_dry_run(self) -> None:
        """Test --dry-run shows preview without creating."""
        tasks_data = {
            "tasks": [
                {
                    "title": "Dry Run Test Task",
                    "task_type": "task",
                    "subtasks": [
                        {"subtask_id": "1.1", "description": "Sub 1"},
                        {"subtask_id": "1.2", "description": "Sub 2"},
                    ],
                }
            ]
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(tasks_data, f)
            f.flush()

            result = runner.invoke(tasks_app, ["create", "--from-file", f.name, "--dry-run"])

            assert result.exit_code == 0
            assert "Would create 1 task(s)" in result.output


class TestAutocodeValidation:
    """Tests for CLI autocode readiness gating."""

    def test_autocode_rejects_task_missing_execution_details(self) -> None:
        mock_client = MagicMock()
        mock_client.project_id = "summitflow"
        task = _make_mock_task(
            "task-mock-1",
            title="Draft feature task",
            task_type="feature",
        )
        # Use a status that bypasses the early "already X" check so readiness is evaluated
        task["status"] = "queue"
        mock_client.get_task.return_value = task
        mock_client.get_subtasks.return_value = {"subtasks": []}
        mock_client.validate_ready.return_value = {
            "ready": False,
            "issues": ["Missing description", "Missing done_when success criteria"],
            "suggestions": ["Add context.files_to_modify/files_to_create for clearer execution scope"],
        }

        with patch("cli.commands.tasks.STClient", return_value=mock_client):
            result = runner.invoke(tasks_app, ["autocode", "task-mock-1"])

        assert result.exit_code == 1
        assert "not execution-ready" in result.output
        assert "Missing description" in result.output


class TestTaskCliErgonomics:
    """Tests for task CLI friction fixes."""

    def test_create_help_hides_legacy_single_task_options(self) -> None:
        result = runner.invoke(tasks_app, ["create", "--help"])

        assert result.exit_code == 0
        assert "--plan" in result.output
        assert "--from-file" in result.output
        assert "st verify plan.json" in result.output
        assert "/schemas/plan" in result.output
        assert "--description" not in result.output
        assert "--autonomous" not in result.output

    def test_subtask_create_help_does_not_advertise_steps(self) -> None:
        result = runner.invoke(subtask_app, ["create", "--help"])

        assert result.exit_code == 0
        assert "--steps" not in result.output

    def test_cli_reference_subtask_create_does_not_advertise_steps(self) -> None:
        from cli.main import CLI_REFERENCE

        assert "--steps" not in CLI_REFERENCE

    def test_verify_help_references_live_plan_schema(self) -> None:
        result = runner.invoke(tasks_app, ["verify", "--help"])

        assert result.exit_code == 0
        assert "/schemas/plan" in result.output
        assert "backend/app/schemas/plan.schema.json" in result.output

    def test_create_rejects_plain_single_task_without_plan(self) -> None:
        result = runner.invoke(tasks_app, ["create", "Draft task"])

        assert result.exit_code == 1
        assert "requires --plan" in result.output
        assert "st verify plan.json" in result.output
        assert "capture <task|bug|idea>" in result.output
        assert "lightweight intake" in result.output

    def test_capture_idea_uses_raw_capture_path(self) -> None:
        mock_client = MagicMock()
        mock_client.create_task.return_value = _make_mock_task(
            "task-mock-idea",
            title="Add dark mode",
            task_type="task",
            priority=3,
            execution_mode="autonomous",
            autonomous=True,
        )

        with (
            patch("cli.commands.tasks_create.require_explicit_project"),
            patch("cli.commands.tasks_create.STClient", return_value=mock_client),
        ):
            result = runner.invoke(tasks_app, ["capture", "idea", "Add dark mode"])

        assert result.exit_code == 0
        mock_client.create_task.assert_called_once()
        payload = mock_client.create_task.call_args.args[0]
        assert payload["title"] == "Add dark mode"
        assert payload["labels"] == ["crowdsourced"]
        assert payload["execution_mode"] == "autonomous"
        assert payload["autonomous"] is True

    def test_capture_bug_routes_to_bug_creator(self) -> None:
        with patch("cli.commands.tasks._create_bug_capture") as mock_capture_bug:
            result = runner.invoke(tasks_app, ["capture", "bug", "Fix auth", "--from", "task-123"])

        assert result.exit_code == 0
        mock_capture_bug.assert_called_once_with("Fix auth", None, 2, None, "task-123")

    def test_capture_bug_marks_bug_autonomous(self) -> None:
        mock_client = MagicMock()
        mock_client.create_task.return_value = _make_mock_task(
            "task-mock-bug",
            title="Fix auth",
            task_type="bug",
            execution_mode="autonomous",
            autonomous=True,
        )

        with (
            patch("cli.commands.tasks.require_explicit_project"),
            patch("cli.commands.tasks.STClient", return_value=mock_client),
            patch("cli.commands.tasks_bug.output_task"),
        ):
            result = runner.invoke(tasks_app, ["capture", "bug", "Fix auth"])

        assert result.exit_code == 0
        payload = mock_client.create_task.call_args.args[0]
        assert payload["task_type"] == "bug"
        assert payload["description"] == "Fix auth"
        assert len(payload["done_when"]) == 3
        assert payload["execution_mode"] == "autonomous"
        assert payload["autonomous"] is True
        mock_client.create_subtask.assert_called_once_with(
            task_id="task-mock-bug",
            subtask_id="1.1",
            description="Reproduce, fix, and verify bug.",
            phase="debugging",
            steps=[
                "Confirm reproduction or recorded failure evidence.",
                "Implement the smallest root-cause fix.",
                "Verify the original symptom and run st check --quick --changed-only.",
            ],
            subtask_type="bug-fix",
        )

    def test_legacy_idea_redirects_to_capture(self) -> None:
        result = runner.invoke(tasks_app, ["idea", "Add dark mode"])

        assert result.exit_code == 1
        assert "removed" in result.output
        assert 'st capture idea "Add dark mode"' in result.output

    def test_list_accepts_local_compact_flag(self) -> None:
        with patch("cli.commands.tasks_list.list_tasks_command") as mock_list:
            result = runner.invoke(tasks_app, ["list", "--compact"])

        assert result.exit_code == 0
        mock_list.assert_called_once()

    def test_context_accepts_local_compact_flag(self) -> None:
        with patch("cli.commands.tasks_context.get_task_context") as mock_get:
            result = runner.invoke(tasks_app, ["context", "task-123", "--compact"])

        assert result.exit_code == 0
        mock_get.assert_called_once()

    def test_export_uses_canonical_export_payload(self) -> None:
        mock_client = MagicMock()
        mock_client.export_task_data.return_value = {
            "exported_at": "2026-04-09T00:00:00+00:00",
            "task": {
                "id": "task-mock-1",
                "title": "Export fidelity task",
                "objective": "Preserve execution-ready task fields on export.",
            },
            "subtasks": [
                {
                    "subtask_id": "1.1",
                    "description": "Keep step detail",
                    "steps": [{"step_number": 1, "description": "Do thing", "passes": False}],
                }
            ],
        }

        with patch("cli.commands.tasks.STClient", return_value=mock_client):
            result = runner.invoke(tasks_app, ["export", "task-mock-1"])

        assert result.exit_code == 0
        mock_client.export_task_data.assert_called_once_with("task-mock-1")
        assert '"objective": "Preserve execution-ready task fields on export."' in result.output
        assert '"description": "Do thing"' in result.output

    def test_log_accepts_trailing_task_id(self) -> None:
        with patch("cli.commands.tasks_commands.append_task_log") as mock_append:
            result = runner.invoke(tasks_app, ["log", "hello world", "task-123"])

        assert result.exit_code == 0
        mock_append.assert_called_once_with("hello world", "task-123", ANY)

    def test_log_accepts_task_id_first(self) -> None:
        with patch("cli.commands.tasks_commands.append_task_log") as mock_append:
            result = runner.invoke(tasks_app, ["log", "task-123", "hello world"])

        assert result.exit_code == 0
        mock_append.assert_called_once_with("hello world", "task-123", ANY)

    def test_log_accepts_explicit_task_option(self) -> None:
        with patch("cli.commands.tasks_commands.append_task_log") as mock_append:
            result = runner.invoke(tasks_app, ["log", "hello world", "--task", "task-123"])

        assert result.exit_code == 0
        mock_append.assert_called_once_with("hello world", "task-123", ANY)

    def test_import_plan_refreshes_subtasks_before_reporting(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "app" / "schemas" / "plan.schema.json"
        plan_path = Path(tempfile.mkdtemp()) / "plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "title": "Import refresh smoke",
                    "objective": "Ensure imported tasks report real subtask counts.",
                    "complexity": "STANDARD",
                    "spirit_anti": "Do not use stale task snapshots after import.",
                    "done_when": ["Import reports one subtask"],
                    "subtasks": [{"id": "1.1", "description": "Implement", "steps": ["Do thing"]}],
                }
            )
        )

        mock_client = MagicMock()
        mock_client.base_url = "http://test"
        mock_client.get.return_value = json.loads(schema_path.read_text())
        mock_client.batch_create_tasks.return_value = {
            "created": [_make_mock_task("task-mock-1", complexity="STANDARD")],
            "errors": [],
        }
        mock_client.get_task.return_value = _make_mock_task("task-mock-1", complexity="STANDARD")
        mock_client.get_subtasks.return_value = {
            "subtasks": [{"subtask_id": "1.1", "description": "Implement", "steps": ["Do thing"]}]
        }

        with patch(
            "cli.commands.tasks_import.upsert_task_spirit_from_plan",
            return_value={"required": True, "stage": "task_shape", "status": "pending"},
        ):
            task, task_id = import_plan_file(plan_path, False, None, mock_client)

        assert task_id == "task-mock-1"
        assert len(task["subtasks"]) == 1
        assert task["subtasks"][0]["subtask_id"] == "1.1"
        assert task["context"]["second_opinion"]["status"] == "pending"

    def test_plan_import_output_surfaces_pending_second_opinion(self) -> None:
        with (
            patch("cli.commands.tasks_create.require_explicit_project"),
            patch("cli.commands.tasks_create.STClient"),
            patch(
                "cli.commands.tasks_create.import_plan_file",
                return_value=(
                    {
                        "complexity": "COMPLEX",
                        "subtasks": [{"subtask_id": "1.1"}],
                        "context": {
                            "second_opinion": {
                                "required": True,
                                "stage": "task_shape",
                                "status": "pending",
                            }
                        },
                    },
                    "task-mock-1",
                ),
            ),
        ):
            result = runner.invoke(tasks_app, ["create", "--plan", "plan.json"])

        assert result.exit_code == 0
        assert "IMPORT:task-mock-1|COMPLEX|1 subtasks|2nd:advisory:task_shape:pending" in result.output

    def test_critique_command_records_second_opinion(self) -> None:
        task = _make_mock_task(
            "task-mock-1",
            title="Critical auth migration",
            task_type="feature",
            complexity="COMPLEX",
            priority=1,
        )
        task["labels"] = ["auth", "backend"]

        mock_client = MagicMock()
        mock_client.complete.return_value = MagicMock(
            content=json.dumps(
                {
                    "verdict": "APPROVED",
                    "summary": "Task definition covers the core auth migration risks.",
                    "missing_requirements": [],
                    "edge_cases": ["Session invalidation during rollout"],
                    "test_gaps": ["Add migration rollback test"],
                    "rollout_gaps": [],
                    "findings": [],
                    "simpler_alternative": "",
                    "confidence": "high",
                }
            )
        )

        with (
            patch("cli.commands.tasks_critique.task_store.get_task", return_value=task),
            patch(
                "cli.commands.tasks_critique.get_task_spirit",
                return_value={
                    "objective": "Ship auth migration safely",
                    "spirit_anti": "Do not break login",
                    "decisions": [{"id": "d1", "title": "Keep routes stable", "outcome": "compat shim"}],
                    "done_when": ["Migration works", "Tests pass"],
                    "context": {"files_to_modify": ["backend/app/auth.py"]},
                },
            ),
            patch("cli.commands.tasks_critique.get_subtasks_for_task", return_value=[]),
            patch("cli.commands.tasks_critique.get_sync_client", return_value=mock_client),
            patch("cli.commands.tasks_critique.persist_second_opinion") as mock_persist,
            patch("cli.commands.tasks_critique.sync_task_execution_readiness"),
            patch("cli.commands.tasks_critique.log_task_event"),
        ):
            result = runner.invoke(tasks_app, ["critique", "task-mock-1"])

        assert result.exit_code == 0
        assert '"verdict": "APPROVED"' in result.output
        call = mock_client.complete.call_args
        assert call.kwargs["use_memory"] is False
        assert call.kwargs["memory_group_id"] is None
        assert "Stage: task_shape" in call.kwargs["messages"][0]["content"]
        persisted = mock_persist.call_args.args[1]
        assert persisted["status"] == "completed"
        assert persisted["stage"] == "task_shape"

    def test_build_review_packet_preserves_dependency_and_step_detail(self) -> None:
        from cli.commands.tasks_critique import _build_review_packet

        task = _make_mock_task("task-mock-1", title="Tighten context output")
        spirit = {
            "objective": "Make context resume reliable",
            "context": {"files_to_modify": ["backend/cli/commands/tasks_context.py"]},
        }
        subtasks = [
            {
                "subtask_id": "2.1",
                "phase": "cli",
                "subtask_type": "implementation",
                "status": "pending",
                "depends_on": ["1.1"],
                "description": "Render continuity block",
                "steps_from_table": [
                    {
                        "step_number": 1,
                        "description": "Wire recent progress logs",
                        "depends_on": [0],
                        "passes": False,
                        "spec": {"detail": "Keep default output short."},
                    }
                ],
            }
        ]

        packet = _build_review_packet(task, spirit, subtasks)

        assert packet["spirit"]["context"] == {
            "files_to_modify": ["backend/cli/commands/tasks_context.py"]
        }
        assert packet["subtasks"][0]["depends_on"] == ["1.1"]
        assert packet["subtasks"][0]["status"] == "pending"
        assert packet["subtasks"][0]["steps"] == [
            {
                "step_number": 1,
                "description": "Wire recent progress logs",
                "depends_on": [0],
                "passes": False,
                "spec": {"detail": "Keep default output short."},
            }
        ]

    def test_build_pre_close_review_packet_uses_passes_guidance_only_steps_and_evidence(self) -> None:
        from cli.commands.tasks_critique import _build_review_packet

        task = _make_mock_task(
            "task-9c551975",
            title="Closeout truth packet",
            status="completed",
        )
        spirit = {
            "objective": "Keep pre-close critique truthful",
            "context": {"files_to_modify": ["backend/cli/commands/tasks_critique.py"]},
        }
        subtasks = [
            {
                "subtask_id": "2.1",
                "phase": "cli",
                "subtask_type": "implementation",
                "status": None,
                "passes": True,
                "description": "Carry closeout truth",
                "steps_source": "plan_context",
                "steps": [
                    {
                        "step_number": 1,
                        "description": "Old guidance step",
                        "passes": False,
                        "depends_on": [0],
                        "spec": {"detail": "context only"},
                    }
                ],
            },
            {
                "subtask_id": "2.2",
                "phase": "cli",
                "subtask_type": "verification",
                "status": "completed",
                "passes": True,
                "description": "Parse evidence",
                "steps_from_table": [
                    {
                        "step_number": 2,
                        "description": "Check packet",
                        "passes": True,
                    }
                ],
            },
        ]
        events = [
            {"message": "EVIDENCE:kind:test|artifact:dt -q -d|state:passed|notes:focused regression"},
            {"message": "noise"},
            {"message": "EVIDENCE:kind:guidance|artifact:opus-review|state:logged"},
            {"message": "EVIDENCE:kind:decision|artifact:migration-scope|state:not-needed"},
            {"message": "EVIDENCE:kind:test|artifact:missing-state"},
        ]

        with patch("cli.commands.tasks_critique.get_events_by_trace", return_value=events):
            packet = _build_review_packet(task, spirit, subtasks, stage="pre_close")

        assert packet["subtasks"][0]["passes"] is True
        assert packet["subtasks"][0]["steps_guidance_only"] is True
        assert packet["subtasks"][0]["steps"] == [
            {
                "step_number": 1,
                "description": "Old guidance step",
                "depends_on": [0],
                "spec": {"detail": "context only"},
            }
        ]
        assert packet["subtasks"][1]["passes"] is True
        assert "steps_guidance_only" not in packet["subtasks"][1]
        assert packet["subtasks"][1]["steps"] == [
            {
                "step_number": 2,
                "description": "Check packet",
                "passes": True,
            }
        ]
        assert packet["closeout"] == {
            "task_status": "completed",
            "completion_ready": True,
            "subtasks_completed": 2,
            "subtasks_total": 2,
            "incomplete_subtasks": [],
            "evidence": [
                {
                    "kind": "test",
                    "artifact": "dt -q -d",
                    "state": "passed",
                    "notes": "focused regression",
                },
                {
                    "kind": "guidance",
                    "artifact": "opus-review",
                    "state": "logged",
                },
                {
                    "kind": "decision",
                    "artifact": "migration-scope",
                    "state": "not-needed",
                },
            ],
            "artifact_flags": {
                "opus_guidance_logged": True,
                "migration_decision_logged": True,
            },
            "active_review": {"stage": "pre_close", "status": "pending"},
        }


    def test_build_pre_close_review_packet_prefers_review_history_over_stale_primary(self) -> None:
        from cli.commands.tasks_critique import _build_review_packet

        task = _make_mock_task("task-mock-history", status="completed")
        spirit = {
            "context": {
                "second_opinion": {
                    "required": True,
                    "stage": "task_shape",
                    "status": "needs_revision",
                    "summary": "Old shape block.",
                    "reviews": {
                        "task_shape": {
                            "required": True,
                            "stage": "task_shape",
                            "status": "needs_revision",
                            "summary": "Old shape block.",
                        },
                        "pre_close": {
                            "required": True,
                            "stage": "pre_close",
                            "status": "completed",
                            "summary": "Closeout proof is sufficient.",
                            "verdict": "APPROVED",
                            "reviewed_at": "2026-01-01T00:00:00+00:00",
                            "reviewed_by_agent": "specifier",
                        },
                    },
                }
            }
        }

        with patch("cli.commands.tasks_critique.get_events_by_trace", return_value=[]):
            packet = _build_review_packet(task, spirit, [], stage="pre_close")

        assert packet["closeout"]["active_review"] == {
            "stage": "pre_close",
            "status": "completed",
            "summary": "Closeout proof is sufficient.",
            "verdict": "APPROVED",
            "reviewed_at": "2026-01-01T00:00:00+00:00",
            "reviewed_by_agent": "specifier",
        }
        assert spirit["context"]["second_opinion"]["stage"] == "task_shape"

    def test_build_pre_close_review_packet_uses_primary_for_both_stage_when_history_missing(self) -> None:
        from cli.commands.tasks_critique import _build_review_packet

        task = _make_mock_task("task-mock-primary", status="completed")
        spirit = {
            "context": {
                "second_opinion": {
                    "required": True,
                    "stage": "both",
                    "status": "completed",
                    "summary": "Primary closeout review.",
                    "verdict": "APPROVED",
                }
            }
        }

        with patch("cli.commands.tasks_critique.get_events_by_trace", return_value=[]):
            packet = _build_review_packet(task, spirit, [], stage="pre_close")

        assert packet["closeout"]["active_review"] == {
            "stage": "both",
            "status": "completed",
            "summary": "Primary closeout review.",
            "verdict": "APPROVED",
        }

    def test_build_pre_close_review_packet_ignores_malformed_or_task_shape_only_primary(self) -> None:
        from cli.commands.tasks_critique import _build_review_packet

        task = _make_mock_task("task-mock-malformed", status="completed")
        spirit = {
            "context": {
                "second_opinion": {
                    "required": True,
                    "stage": "task_shape",
                    "status": "needs_revision",
                    "summary": "Shape still old.",
                    "reviews": {"pre_close": "bad-payload"},
                }
            }
        }

        with patch("cli.commands.tasks_critique.get_events_by_trace", return_value=[]):
            packet = _build_review_packet(task, spirit, [], stage="pre_close")

        assert packet["closeout"]["active_review"] == {"stage": "pre_close", "status": "pending"}
        assert spirit["context"]["second_opinion"]["reviews"]["pre_close"] == "bad-payload"

    def test_build_pre_close_review_packet_accepts_timestamped_evidence_entries(self) -> None:
        from cli.commands.tasks_critique import _build_review_packet

        task = _make_mock_task("task-mock-timestamped", status="completed")
        subtasks = [
            {
                "subtask_id": "5.1",
                "status": "completed",
                "passes": True,
                "description": "Timestamped evidence should still count",
            }
        ]
        events = [
            {
                "message": "[2026-04-22T06:00:50Z] EVIDENCE:kind:proof|artifact:artifacts/closeout.md|state:recorded"
            }
        ]

        with patch("cli.commands.tasks_critique.get_events_by_trace", return_value=events):
            packet = _build_review_packet(task, None, subtasks, stage="pre_close")

        assert packet["closeout"]["evidence"] == [
            {
                "kind": "proof",
                "artifact": "artifacts/closeout.md",
                "state": "recorded",
            }
        ]
        assert packet["closeout"]["artifact_flags"] == {
            "opus_guidance_logged": False,
            "migration_decision_logged": False,
        }

    def test_build_pre_close_review_packet_accepts_shorthand_kind_evidence_entries(self) -> None:
        from cli.commands.tasks_critique import _build_review_packet

        task = _make_mock_task("task-mock-shorthand", status="completed")
        subtasks = [
            {
                "subtask_id": "5.1b",
                "status": "completed",
                "passes": True,
                "description": "Shorthand evidence kind should still parse",
            }
        ]
        events = [
            {
                "message": "[2026-04-22T06:00:50Z] EVIDENCE:proof|artifact:artifacts/closeout.md|state:recorded"
            }
        ]

        with patch("cli.commands.tasks_critique.get_events_by_trace", return_value=events):
            packet = _build_review_packet(task, None, subtasks, stage="pre_close")

        assert packet["closeout"]["evidence"] == [
            {
                "kind": "proof",
                "artifact": "artifacts/closeout.md",
                "state": "recorded",
            }
        ]

    def test_build_pre_close_review_packet_reads_past_large_noise_history_for_evidence(self) -> None:
        from cli.commands.tasks_critique import _build_review_packet

        task = _make_mock_task("task-mock-deep-history", status="completed")
        subtasks = [
            {
                "subtask_id": "5.2",
                "status": "completed",
                "passes": True,
                "description": "Evidence should survive long task history",
            }
        ]
        all_events = [
            {"message": f"noise-{idx}"}
            for idx in range(600)
        ] + [
            {
                "message": "[2026-04-22T06:01:00Z] EVIDENCE:kind:test|artifact:artifacts/full-check.txt|state:passed"
            }
        ]

        def _mock_get_events_by_trace(
            trace_id: str,
            *,
            visibility: str | None = None,
            level: str | None = None,
            after: object | None = None,
            from_sequence: object | None = None,
            limit: int = 1000,
        ) -> list[dict[str, str]]:
            assert trace_id == "task-mock-deep-history"
            assert visibility == "user"
            return all_events[:limit]

        with patch("cli.commands.tasks_critique.get_events_by_trace", side_effect=_mock_get_events_by_trace):
            packet = _build_review_packet(task, None, subtasks, stage="pre_close")

        assert packet["closeout"]["evidence"] == [
            {
                "kind": "test",
                "artifact": "artifacts/full-check.txt",
                "state": "passed",
            }
        ]

    def test_build_pre_close_review_packet_surfaces_incomplete_subtasks_and_zero_subtask_ready(self) -> None:
        from cli.commands.tasks_critique import _build_review_packet

        task = _make_mock_task("task-mock-2", status="in_progress")

        with patch("cli.commands.tasks_critique.get_events_by_trace", return_value=[]):
            empty_packet = _build_review_packet(task, None, [], stage="pre_close")
            incomplete_packet = _build_review_packet(
                task,
                None,
                [
                    {
                        "subtask_id": "3.1",
                        "status": "completed",
                        "passes": False,
                        "description": "Missing proof",
                    }
                ],
                stage="pre_close",
            )

        assert empty_packet["closeout"] == {
            "task_status": "in_progress",
            "completion_ready": True,
            "subtasks_completed": 0,
            "subtasks_total": 0,
            "incomplete_subtasks": [],
            "evidence": [],
            "artifact_flags": {
                "opus_guidance_logged": False,
                "migration_decision_logged": False,
            },
            "active_review": {"stage": "pre_close", "status": "pending"},
        }
        assert incomplete_packet["closeout"]["completion_ready"] is False
        assert incomplete_packet["closeout"]["subtasks_completed"] == 0
        assert incomplete_packet["closeout"]["subtasks_total"] == 1
        assert incomplete_packet["closeout"]["incomplete_subtasks"] == ["3.1"]

    def test_build_pre_close_review_packet_prefers_passes_over_status(self) -> None:
        from cli.commands.tasks_critique import _build_review_packet

        task = _make_mock_task("task-mock-3", status="completed")
        subtasks = [
            {
                "subtask_id": "4.1",
                "status": "pending",
                "passes": True,
                "description": "Done despite stale status",
            },
            {
                "subtask_id": "4.2",
                "status": "completed",
                "passes": False,
                "description": "Not done despite status",
            },
        ]

        with patch("cli.commands.tasks_critique.get_events_by_trace", return_value=[]):
            packet = _build_review_packet(task, None, subtasks, stage="pre_close")

        assert packet["subtasks"][0]["status"] == "pending"
        assert packet["subtasks"][0]["passes"] is True
        assert packet["subtasks"][1]["status"] == "completed"
        assert packet["subtasks"][1]["passes"] is False
        assert packet["closeout"]["subtasks_completed"] == 1
        assert packet["closeout"]["incomplete_subtasks"] == ["4.2"]
        assert packet["closeout"]["completion_ready"] is False

    def test_build_task_shape_review_packet_keeps_legacy_shape_without_closeout_fields(self) -> None:
        from cli.commands.tasks_critique import _build_review_packet

        task = _make_mock_task("task-shape-boundary")
        subtasks = [
            {
                "subtask_id": "1.1",
                "status": "pending",
                "passes": True,
                "description": "Legacy task-shape packet should stay narrow",
                "steps_source": "plan_context",
                "steps": [
                    {
                        "step_number": 1,
                        "description": "Guidance stays guidance only in pre-close",
                        "passes": False,
                    }
                ],
            }
        ]

        packet = _build_review_packet(task, None, subtasks, stage="task_shape")

        assert list(packet.keys()) == ["task", "spirit", "subtasks"]
        assert "closeout" not in packet
        assert packet["subtasks"][0] == {
            "subtask_id": "1.1",
            "status": "pending",
            "description": "Legacy task-shape packet should stay narrow",
            "steps": [
                {
                    "step_number": 1,
                    "description": "Guidance stays guidance only in pre-close",
                    "passes": False,
                }
            ],
        }

    def test_build_pre_close_review_packet_treats_null_and_missing_passes_as_incomplete(self) -> None:
        from cli.commands.tasks_critique import _build_review_packet

        task = _make_mock_task("task-null-passes", status="completed")
        subtasks = [
            {
                "subtask_id": "6.1",
                "status": "completed",
                "passes": None,
                "description": "Null passes should remain incomplete",
            },
            {
                "subtask_id": "6.2",
                "status": "completed",
                "description": "Missing passes should remain incomplete",
            },
            {
                "subtask_id": "6.3",
                "status": "pending",
                "passes": True,
                "description": "Explicit pass counts as complete",
            },
        ]

        with patch("cli.commands.tasks_critique.get_events_by_trace", return_value=[]):
            packet = _build_review_packet(task, None, subtasks, stage="pre_close")

        assert packet["closeout"]["completion_ready"] is False
        assert packet["closeout"]["subtasks_completed"] == 1
        assert packet["closeout"]["subtasks_total"] == 3
        assert packet["closeout"]["incomplete_subtasks"] == ["6.1", "6.2"]

    def test_build_pre_close_review_packet_requests_only_user_visible_events(self) -> None:
        from cli.commands.tasks_critique import _build_review_packet

        task = _make_mock_task("task-user-visible", status="completed")
        subtasks = [{"subtask_id": "7.1", "status": "completed", "passes": True, "description": "Only user evidence counts"}]

        def _mock_get_events_by_trace(
            trace_id: str,
            *,
            visibility: str | None = None,
            level: str | None = None,
            after: object | None = None,
            from_sequence: object | None = None,
            limit: int = 1000,
        ) -> list[dict[str, str]]:
            assert trace_id == "task-user-visible"
            assert visibility == "user"
            return [{"message": "EVIDENCE:kind:test|artifact:user-proof|state:passed"}]

        with patch("cli.commands.tasks_critique.get_events_by_trace", side_effect=_mock_get_events_by_trace):
            packet = _build_review_packet(task, None, subtasks, stage="pre_close")

        assert packet["closeout"]["evidence"] == [
            {"kind": "test", "artifact": "user-proof", "state": "passed"}
        ]

    def test_build_pre_close_review_packet_keeps_conflicting_evidence_in_order_and_ignores_malformed_lines(self) -> None:
        from cli.commands.tasks_critique import _build_review_packet

        task = _make_mock_task("task-evidence-parser", status="completed")
        subtasks = [{"subtask_id": "8.1", "status": "completed", "passes": True, "description": "Evidence parser coverage"}]
        events = [
            {
                "message": "EVIDENCE:kind:test|artifact:first-artifact|artifact:final-artifact|state:passed|unknown:drop-me"
            },
            {"message": "EVIDENCE:kind:test|artifact:final-artifact|state:failed|notes:conflict kept"},
            {"message": "EVIDENCE:kind:test|artifact:missing-state"},
            {"message": "EVIDENCE:kind:test|state:missing-artifact"},
        ]

        with patch("cli.commands.tasks_critique.get_events_by_trace", return_value=events):
            packet = _build_review_packet(task, None, subtasks, stage="pre_close")

        assert packet["closeout"]["evidence"] == [
            {"kind": "test", "artifact": "final-artifact", "state": "passed"},
            {
                "kind": "test",
                "artifact": "final-artifact",
                "state": "failed",
                "notes": "conflict kept",
            },
        ]

    def test_build_pre_close_review_packet_returns_empty_evidence_and_false_flags_on_lookup_error(self) -> None:
        from cli.commands.tasks_critique import _build_review_packet

        task = _make_mock_task("task-evidence-error", status="pending")
        subtasks = [{"subtask_id": "9.1", "status": "completed", "passes": True, "description": "Evidence lookup failures should degrade cleanly"}]

        with patch("cli.commands.tasks_critique.get_events_by_trace", side_effect=RuntimeError("boom")):
            packet = _build_review_packet(task, None, subtasks, stage="pre_close")

        assert packet["closeout"] == {
            "task_status": "pending",
            "completion_ready": True,
            "subtasks_completed": 1,
            "subtasks_total": 1,
            "incomplete_subtasks": [],
            "evidence": [],
            "artifact_flags": {
                "opus_guidance_logged": False,
                "migration_decision_logged": False,
            },
            "active_review": {"stage": "pre_close", "status": "pending"},
        }

    def test_build_request_message_changes_with_stage(self) -> None:
        from cli.commands.tasks_critique import _build_request_message

        packet = {"task": {"id": "task-mock-1"}, "spirit": {}, "subtasks": []}

        task_shape = _build_request_message(packet, stage="task_shape")
        pre_close = _build_request_message(packet, stage="pre_close")

        assert "implementation can start safely" in task_shape
        assert "ready to close" in pre_close
        assert "rollout, migration, or monitoring only when materially affected" in task_shape
        assert "Return strict JSON only" in task_shape

    def test_critique_command_rejects_invalid_stage(self) -> None:
        result = runner.invoke(tasks_app, ["critique", "task-mock-1", "--stage", "nonsense"])

        assert result.exit_code == 1
        assert "Unsupported critique stage: nonsense" in result.output


class TestPlanSchemaConsistency:
    """Tests for plan schema and import ergonomics."""

    def test_plan_schema_allows_string_steps(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "app" / "schemas" / "plan.schema.json"
        schema = json.loads(schema_path.read_text())
        plan = {
            "title": "Schema smoke task",
            "objective": "Validate that string steps are accepted in plan subtasks.",
            "complexity": "STANDARD",
            "spirit_anti": "Do not reject valid string steps.",
            "done_when": ["Schema validation passes"],
            "subtasks": [
                {"id": "1.1", "description": "Implement", "steps": ["Do thing", {"description": "Verify thing"}]}
            ],
        }

        jsonschema.validate(plan, schema)

    def test_complex_plan_validation_surfaces_decisions_requirement(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "app" / "schemas" / "plan.schema.json"
        mock_client = MagicMock()
        mock_client.base_url = "http://test"
        mock_client.get.return_value = json.loads(schema_path.read_text())
        mock_client.batch_create_tasks.return_value = {
            "created": [_make_mock_task("task-mock-1", complexity="COMPLEX")],
            "errors": [],
        }
        mock_client.get_task.return_value = _make_mock_task("task-mock-1", complexity="COMPLEX")
        mock_client.get_subtasks.return_value = {
            "subtasks": [{"subtask_id": "1.1", "description": "Implement", "steps": ["Do thing"]}]
        }

        plan_path = Path(tempfile.mkdtemp()) / "complex-plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "title": "Complex schema smoke",
                    "objective": "Validate authoring guidance",
                    "complexity": "COMPLEX",
                    "spirit_anti": "Do not hide missing decisions guidance.",
                    "done_when": ["Validation passes for COMPLEX without decisions"],
                    "subtasks": [{"id": "1.1", "description": "Implement", "steps": ["Do thing"]}],
                }
            )
        )

        with (
            patch("cli.commands.tasks_create.require_explicit_project"),
            patch("cli.commands.tasks_create.STClient", return_value=mock_client),
            patch("cli.commands.tasks_import.upsert_task_spirit_from_plan", return_value=None),
        ):
            result = runner.invoke(tasks_app, ["create", "--plan", str(plan_path)])

        # decisions requirement was removed — COMPLEX plans without decisions are now accepted
        assert result.exit_code == 0
        assert "IMPORT:task-mock-1|COMPLEX" in result.output

    def test_plan_schema_accepts_second_opinion_context(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "app" / "schemas" / "plan.schema.json"
        schema = json.loads(schema_path.read_text())
        plan = {
            "title": "Second opinion schema smoke",
            "objective": "Validate second-opinion metadata in task plans.",
            "complexity": "COMPLEX",
            "spirit_anti": "Do not omit critique metadata for high-risk work.",
            "done_when": ["Schema validation passes"],
            "decisions": [{"id": "d1", "title": "Require task-shape critique", "outcome": "yes"}],
            "context": {
                "second_opinion": {
                    "required": True,
                    "stage": "task_shape",
                    "status": "completed",
                    "summary": "Independent critique reviewed the plan.",
                    "confidence": "high",
                }
            },
        }

        jsonschema.validate(plan, schema)

    def test_plan_schema_accepts_execution_contract(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "app" / "schemas" / "plan.schema.json"
        schema = json.loads(schema_path.read_text())
        plan = {
            "title": "Execution contract schema smoke",
            "objective": "Validate runtime-evaluation contract metadata in task plans.",
            "complexity": "STANDARD",
            "done_when": ["Schema validation passes"],
            "execution_contract": {
                "mode": "runtime_eval_plus_design",
                "target_urls": ["/"],
                "user_flows": [
                    {
                        "title": "Open the home page",
                        "actions": ["Visit /"],
                        "expected_outcomes": ["The hero renders"],
                    }
                ],
                "api_checks": [{"method": "GET", "path": "/api/health", "status": 200}],
                "design_criteria": {"rubric": ["clarity", "craft"]},
                "risk_notes": ["Responsive layout can regress during polish."],
            },
            "context": {
                "files_to_modify": ["frontend/src/app/page.tsx"],
                "testing_strategy": "Use st browser to verify the landing page route.",
            },
        }

        jsonschema.validate(plan, schema)


class TestCreateFromFileErrors:
    """Test error handling for st create --from-file.

    These tests verify validation errors - no mocking needed since they fail before API calls.
    """

    @pytest.fixture(autouse=True)
    def _bypass_project_check(self) -> Generator[None]:
        """Bypass require_explicit_project since tests invoke tasks_app directly."""
        with patch("cli.commands.tasks_import.require_explicit_project"):
            yield

    def test_invalid_json_syntax(self) -> None:
        """Test handling of invalid JSON syntax."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"tasks": [invalid json')
            f.flush()

            result = runner.invoke(tasks_app, ["create", "--from-file", f.name])

            assert result.exit_code == 1
            assert "Invalid JSON" in result.output

    def test_missing_tasks_array(self) -> None:
        """Test handling of missing 'tasks' key."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"items": []}, f)
            f.flush()

            result = runner.invoke(tasks_app, ["create", "--from-file", f.name])

            assert result.exit_code == 1
            assert "must contain a 'tasks' array" in result.output

    def test_missing_required_fields(self) -> None:
        """Test handling of missing required fields."""
        tasks_data = {
            "tasks": [
                {"description": "Missing title and task_type"},
            ]
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(tasks_data, f)
            f.flush()

            result = runner.invoke(tasks_app, ["create", "--from-file", f.name])

            assert result.exit_code == 1
            assert "Missing required field 'title'" in result.output
            assert "Missing required field 'task_type'" in result.output

    def test_invalid_task_type(self) -> None:
        """Test handling of invalid task_type."""
        tasks_data = {
            "tasks": [
                {"title": "Test", "task_type": "invalid_type"},
            ]
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(tasks_data, f)
            f.flush()

            result = runner.invoke(tasks_app, ["create", "--from-file", f.name])

            assert result.exit_code == 1
            assert "task_type must be one of" in result.output

    def test_invalid_priority(self) -> None:
        """Test handling of invalid priority."""
        tasks_data = {
            "tasks": [
                {"title": "Test", "task_type": "task", "priority": 10},
            ]
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(tasks_data, f)
            f.flush()

            result = runner.invoke(tasks_app, ["create", "--from-file", f.name])

            assert result.exit_code == 1
            assert "priority must be integer 0-4" in result.output

    def test_file_not_found(self) -> None:
        """Test handling of non-existent file."""
        result = runner.invoke(tasks_app, ["create", "--from-file", "/nonexistent/file.json"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "no such file" in result.output.lower()


class TestSubtaskCreate:
    """Test st subtask create command.

    These tests check subtask creation validation.
    Since they test CLI commands that need task existence, we use mock_st_client.
    """

    def test_subtask_create_succeeds(self, mock_st_client: tuple[MagicMock, dict[str, dict[str, Any]]]) -> None:
        """Test creating a subtask succeeds."""
        mock_client, _tasks_db = mock_st_client
        task = mock_client.create_task(
            {
                "title": "CLI Subtask Test",
                "task_type": "task",
                "priority": 3,
            }
        )

        mock_client.create_subtask = MagicMock(
            return_value=_make_mock_subtask(task["id"], "1.1", description="Test subtask")
        )

        with patch("cli.commands.subtask.STClient", return_value=mock_client):
            result = runner.invoke(
                subtask_app,
                [
                    "create",
                    "1.1",
                    "-d",
                    "Test subtask description",
                    "--task",
                    task["id"],
                    "--phase",
                    "backend",
                ],
            )

            assert result.exit_code == 0


class TestBackupCommands:
    """Test st backup commands.

    These tests check backup commands work - they read from DB but don't create tasks.
    """

    @pytest.fixture(autouse=True)
    def set_project_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Set ST_PROJECT_ID for all backup tests."""
        monkeypatch.setenv("ST_PROJECT_ID", "summitflow")

    @pytest.fixture()
    def mock_backup_config(self):
        """Shared Config fixture for backup command tests."""
        from cli.config import Config

        return Config(
            api_base="http://localhost:8000",
            project_id="summitflow",
            project_root="/tmp/test-project",
            source="test",
        )

    @pytest.fixture(autouse=True)
    def mock_backup_apis(self) -> Generator[None]:
        """Keep backup CLI tests off the live API."""
        mock_project_api = MagicMock()
        mock_project_api.list_backups.return_value = {"backups": [], "total": 0}
        mock_project_api.latest_backup.return_value = None

        mock_source_api = MagicMock()
        mock_source_api.list_source_backups.return_value = {"backups": [], "total": 0}

        with (
            patch("cli.commands.backup._get_project_api", return_value=mock_project_api),
            patch("cli.commands.backup._get_source_api", return_value=mock_source_api),
        ):
            yield

    def test_backup_list(self) -> None:
        """Test st backup list command."""
        from cli.commands.backup import app as backup_app

        result = runner.invoke(backup_app, ["list"])
        # Should succeed even with no backups
        assert result.exit_code == 0

    def test_backup_list_compact(self) -> None:
        """Test st --compact backup list outputs TOON format."""
        from cli.commands.backup import app as backup_app
        from cli.output import set_compact_output

        # Enable compact mode
        set_compact_output(True)
        try:
            result = runner.invoke(backup_app, ["list"])
            assert result.exit_code == 0
            assert "BACKUPS[" in result.output
        finally:
            set_compact_output(False)

    def test_backup_schedule_view(self) -> None:
        """Test st backup schedule --help shows usage."""
        from cli.commands.backup import app as backup_app

        result = runner.invoke(backup_app, ["schedule", "--help"])
        # schedule requires a source_id argument; verify help works
        assert result.exit_code == 0
        assert "SOURCE_ID" in result.output

    def test_backup_status(self) -> None:
        """Test st backup status shows latest backup."""
        from cli.commands.backup import app as backup_app

        result = runner.invoke(backup_app, ["status"])
        # Should succeed even with no backups
        assert result.exit_code == 0

    def test_backup_create_help(self) -> None:
        """Test st backup create --help."""
        from cli.commands.backup import app as backup_app

        result = runner.invoke(backup_app, ["create", "--help"])
        assert result.exit_code == 0
        assert "--note" in result.output
        assert "--keep-local" in result.output

    def test_backup_restore_help(self) -> None:
        """Test st backup restore --help."""
        from cli.commands.backup import app as backup_app

        result = runner.invoke(backup_app, ["restore", "--help"])
        assert result.exit_code == 0
        assert "--dry-run" in result.output
        assert "--source" in result.output

    def test_backup_create_compact_without_task_id_uses_message(self, mock_backup_config) -> None:
        """Backup create should not print `None` when the backend omits task_id."""
        from cli.commands.backup import app as backup_app
        from cli.output import set_compact_output

        mock_config = mock_backup_config

        with (
            patch("cli.commands.backup._get_project_api") as mock_api_factory,
            patch("cli.commands.backup.get_config", return_value=mock_config),
        ):
            mock_api = MagicMock()
            mock_api.create_backup.return_value = {
                "status": "queued",
                "message": "Backup task queued for project summitflow",
            }
            mock_api_factory.return_value = mock_api

            set_compact_output(True)
            try:
                result = runner.invoke(backup_app, ["create", "--note", "test"])
            finally:
                set_compact_output(False)

        assert result.exit_code == 0
        assert "QUEUED | project:summitflow | Backup task queued for project summitflow" in result.output
        assert "None" not in result.output

    def test_backup_restore_dry_run_compact_without_task_id_uses_backup_id(self, mock_backup_config) -> None:
        """Backup restore dry-run should emit the backup id when no task_id exists."""
        from cli.commands.backup import app as backup_app
        from cli.output import set_compact_output

        mock_config = mock_backup_config

        with (
            patch("cli.commands.backup._get_project_api") as mock_api_factory,
            patch("cli.commands.backup.get_config", return_value=mock_config),
        ):
            mock_api = MagicMock()
            mock_api.get_backup.return_value = {"id": "bkp-123"}
            mock_api.restore_backup.return_value = {
                "status": "queued",
                "message": "Restore task queued for backup bkp-123",
            }
            mock_api_factory.return_value = mock_api

            set_compact_output(True)
            try:
                result = runner.invoke(backup_app, ["restore", "bkp-123", "--dry-run"])
            finally:
                set_compact_output(False)

        assert result.exit_code == 0
        assert "QUEUED | dry-run | backup:bkp-123 | project:summitflow" in result.output
        assert "None" not in result.output

    def test_backup_restore_requires_confirm_for_non_dry_run(self, mock_backup_config) -> None:
        """Backup restore should use two-pass confirmation before mutating."""
        from cli.commands.backup import app as backup_app

        mock_config = mock_backup_config

        with (
            patch("cli.commands.backup._get_project_api") as mock_api_factory,
            patch("cli.commands.backup.get_config", return_value=mock_config),
            patch("cli.commands.backup.confirm_gate") as confirm_gate,
        ):
            mock_api = MagicMock()
            mock_api.get_backup.return_value = {"id": "bkp-123"}
            mock_api.restore_backup.return_value = {"status": "queued", "message": "Restore queued"}
            mock_api_factory.return_value = mock_api

            result = runner.invoke(backup_app, ["restore", "bkp-123", "--confirm", "abc12345"])

        assert result.exit_code == 0
        confirm_gate.assert_called_once()
        mock_api.restore_backup.assert_called_once_with("bkp-123", dry_run=False)

    def test_backup_restore_archive_dry_run_previews_natively(self, tmp_path: Path) -> None:
        """Archive restore dry-run should preview without legacy script delegation."""
        from cli.commands.backup import app as backup_app

        archive = tmp_path / "summitflow.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            payload = tmp_path / "file.txt"
            payload.write_text("ok")
            tar.add(payload, arcname="summitflow/file.txt")

        result = runner.invoke(backup_app, ["restore", "--file", str(archive), "--dry-run", "--files-only"])
        assert result.exit_code == 0
        assert "ARCHIVE" in result.output
        assert "summitflow/file.txt" in result.output


class TestVerifyPlanGates:
    """Test st verify command validates plan structure.

    Steps are now optional in plans (subtasks can have steps added later).
    Verification focuses on: schema compliance, complexity requirements, dep refs.
    """

    @pytest.fixture(autouse=True)
    def mock_verify_schema(self) -> Generator[None]:
        """Mock schema fetch so verify tests stay local."""
        mock_client = MagicMock()
        mock_client.base_url = "http://localhost:8000"
        mock_client.get.return_value = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "objective": {"type": "string"},
                "task_type": {"type": "string"},
                "complexity": {"type": "string"},
                "subtasks": {"type": "array"},
                "done_when": {"type": "array"},
            },
            "required": ["title", "objective", "task_type", "complexity", "subtasks"],
        }

        with patch("cli.commands.tasks.STClient", return_value=mock_client):
            yield

    def test_verify_accepts_subtask_without_steps(self) -> None:
        """st verify accepts subtasks that have no steps (steps added later)."""
        plan = {
            "title": "Test plan with no steps",
            "objective": "Test objective that is long enough to pass validation",
            "task_type": "task",
            "complexity": "SIMPLE",
            "subtasks": [
                {
                    "id": "1.1",
                    "description": "Subtask without steps — valid",
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(plan, f)
            f.flush()

            result = runner.invoke(tasks_app, ["verify", f.name])

            # Subtasks without steps are now valid
            assert result.exit_code == 0

    def test_verify_rejects_invalid_dependency_ref(self) -> None:
        """st verify rejects plans with depends_on referencing non-existent subtasks."""
        plan = {
            "title": "Test plan with bad dep",
            "objective": "Test objective",
            "task_type": "task",
            "complexity": "SIMPLE",
            "subtasks": [
                {"id": "1.1", "description": "First", "depends_on": ["1.99"]},
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(plan, f)
            f.flush()

            result = runner.invoke(tasks_app, ["verify", f.name])

            assert result.exit_code == 1
            assert "1.99" in result.output


    def test_build_pre_close_review_packet_falls_back_to_pending_for_legacy_primary_task_shape(self) -> None:
        from cli.commands.tasks_critique import _build_review_packet

        task = _make_mock_task("task-mock-legacy", status="completed")
        spirit = {
            "context": {
                "second_opinion": {
                    "required": True,
                    "stage": "task_shape",
                    "status": "needs_revision",
                    "summary": "Legacy shape note.",
                }
            }
        }

        with patch("cli.commands.tasks_critique.get_events_by_trace", return_value=[]):
            packet = _build_review_packet(task, spirit, [], stage="pre_close")

        assert packet["closeout"]["active_review"] == {"stage": "pre_close", "status": "pending"}
