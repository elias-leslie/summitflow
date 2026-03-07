"""Tests for CLI commands.

Tests the st CLI commands including batch creation from file.

IMPORTANT: All tests use mocked storage/client to avoid hitting production DB.
This file tests CLI behavior with mocked backends - it does NOT create real tasks.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from cli.commands.step import app as step_app
from cli.commands.subtask import app as subtask_app
from cli.commands.tasks import app as tasks_app

runner = CliRunner()


def _make_mock_task(task_id: str, **kwargs: Any) -> dict[str, Any]:
    """Create a mock task dict with default values."""
    return {
        "id": task_id,
        "project_id": kwargs.get("project_id", "summitflow"),
        "capability_id": None,
        "title": kwargs.get("title", "Mock Task"),
        "description": kwargs.get("description"),
        "status": "pending",
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
        mock_client.get_task.return_value = _make_mock_task(
            "task-mock-1",
            title="Draft feature task",
            task_type="feature",
        )
        mock_client.get_subtasks.return_value = {"subtasks": []}
        mock_client.validate_ready.return_value = {
            "ready": False,
            "issues": ["Missing objective", "Missing done_when success criteria"],
            "suggestions": ["Add context.files_to_modify/files_to_create for clearer execution scope"],
        }

        with patch("cli.commands.tasks.STClient", return_value=mock_client):
            result = runner.invoke(tasks_app, ["autocode", "task-mock-1"])

        assert result.exit_code == 1
        assert "not execution-ready" in result.output
        assert "Missing objective" in result.output


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

    def test_subtask_create_requires_steps(self, mock_st_client: tuple[MagicMock, dict[str, dict[str, Any]]]) -> None:
        """Test that creating a subtask without steps fails."""
        # Create mock task first
        mock_client, _tasks_db = mock_st_client
        task = mock_client.create_task(
            {
                "title": "CLI Subtask Test",
                "task_type": "task",
                "priority": 3,
            }
        )

        # Also mock the subtask CLI's client
        with patch("cli.commands.subtask.STClient", return_value=mock_client):
            # Subtask without steps should fail (gate rejects)
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

            assert result.exit_code == 1
            assert "steps are required" in result.output.lower()

    def test_subtask_create_with_steps_json(self, mock_st_client: tuple[MagicMock, dict[str, dict[str, Any]]]) -> None:
        """Test creating a subtask with proper step structure via --steps-json."""
        mock_client, _tasks_db = mock_st_client
        task = mock_client.create_task(
            {
                "title": "CLI Subtask Steps Test",
                "task_type": "task",
                "priority": 3,
            }
        )

        # Mock create_subtask to return success
        mock_client.create_subtask = MagicMock(
            return_value=_make_mock_subtask(task["id"], "1.1", description="Test with steps")
        )

        with patch("cli.commands.subtask.STClient", return_value=mock_client):
            # Use --steps-json with step descriptions
            steps_json = json.dumps(
                [
                    {
                        "description": "First step",
                    },
                    {
                        "description": "Second step",
                    },
                ]
            )

            result = runner.invoke(
                subtask_app,
                [
                    "create",
                    "1.1",
                    "-d",
                    "Test with steps",
                    "--task",
                    task["id"],
                    "--steps-json",
                    steps_json,
                ],
            )

            assert result.exit_code == 0
            # Default output is JSON
            assert '"success": true' in result.output
            assert '"message": "1.1"' in result.output

class TestStepCreate:
    """Test st step create command.

    These tests verify step creation - currently skipped as they require
    more complex mocking of the step storage layer.
    """

    @pytest.mark.skip(
        reason="Requires complex storage mocking - use integration tests for full flow"
    )
    def test_step_create(self, mock_storage: dict[str, Any]) -> None:
        """Test creating steps for a subtask."""
        pass

    def test_step_new_invalid_task(self) -> None:
        """Test error when creating steps for non-existent task."""
        from cli.client import APIError

        mock_client = MagicMock()
        mock_client.create_step_with_verification = MagicMock(
            side_effect=APIError(404, "Task not found")
        )

        with patch("cli.commands.step_operations.STClient", return_value=mock_client):
            result = runner.invoke(
                step_app,
                [
                    "new",
                    "1.1",  # subtask_id
                    "Step one",  # description
                    "--task",
                    "task-nonexistent",
                ],
            )

            assert result.exit_code == 1
            assert "not found" in result.output.lower() or "404" in result.output


class TestBackupCommands:
    """Test st backup commands.

    These tests check backup commands work - they read from DB but don't create tasks.
    """

    @pytest.fixture(autouse=True)
    def set_project_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Set ST_PROJECT_ID for all backup tests."""
        monkeypatch.setenv("ST_PROJECT_ID", "summitflow")

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


class TestVerifyPlanGates:
    """Test st verify command validates plan structure.

    Steps are now optional in plans (subtasks can have steps added later).
    Verification focuses on: schema compliance, complexity requirements, dep refs.
    """

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
