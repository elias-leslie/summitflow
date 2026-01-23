"""Tests for CLI commands.

Tests the st CLI commands including batch creation from file.
"""

from __future__ import annotations

import contextlib
import json
import tempfile

import pytest
from typer.testing import CliRunner

from app.storage import tasks as task_store
from cli.commands.step import app as step_app
from cli.commands.subtask import app as subtask_app
from cli.commands.tasks import app as tasks_app

runner = CliRunner()


@pytest.fixture
def cleanup_test_tasks():
    """Clean up test tasks after tests."""
    task_ids: list[str] = []
    yield task_ids
    # Cleanup
    for task_id in task_ids:
        with contextlib.suppress(Exception):
            task_store.delete_task(task_id)


class TestCreateFromFile:
    """Test st create --from-file functionality."""

    def test_from_file_valid_json(self, cleanup_test_tasks):
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

            # Extract task IDs from output and add to cleanup
            for line in result.output.split("\n"):
                if line.strip().startswith("✓ task-"):
                    task_id = line.split(":")[0].strip().replace("✓ ", "")
                    cleanup_test_tasks.append(task_id)

    def test_from_file_with_subtasks(self, cleanup_test_tasks):
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

            # Extract task ID and verify subtask was created
            for line in result.output.split("\n"):
                if line.strip().startswith("✓ task-"):
                    task_id = line.split(":")[0].strip().replace("✓ ", "")
                    cleanup_test_tasks.append(task_id)

                    # Verify subtask exists
                    task = task_store.get_task(task_id)
                    assert task is not None

    def test_from_file_dry_run(self):
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
            assert "Dry Run Test Task" in result.output
            assert "2 subtask(s)" in result.output


class TestCreateFromFileErrors:
    """Test error handling for st create --from-file."""

    def test_invalid_json_syntax(self):
        """Test handling of invalid JSON syntax."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"tasks": [invalid json')
            f.flush()

            result = runner.invoke(tasks_app, ["create", "--from-file", f.name])

            assert result.exit_code == 1
            assert "Invalid JSON" in result.output

    def test_missing_tasks_array(self):
        """Test handling of missing 'tasks' key."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"items": []}, f)
            f.flush()

            result = runner.invoke(tasks_app, ["create", "--from-file", f.name])

            assert result.exit_code == 1
            assert "must contain a 'tasks' array" in result.output

    def test_missing_required_fields(self):
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

    def test_invalid_task_type(self):
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

    def test_invalid_priority(self):
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

    def test_file_not_found(self):
        """Test handling of non-existent file."""
        result = runner.invoke(tasks_app, ["create", "--from-file", "/nonexistent/file.json"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "no such file" in result.output.lower()


class TestSubtaskCreate:
    """Test st subtask create command."""

    def test_subtask_create_requires_steps(self, cleanup_test_tasks):
        """Test that creating a subtask without steps fails."""
        task = task_store.create_task(
            project_id="summitflow",
            title="CLI Subtask Test",
            task_type="task",
            priority=3,
        )
        cleanup_test_tasks.append(task["id"])

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

    def test_subtask_create_with_steps_json(self, cleanup_test_tasks):
        """Test creating a subtask with proper step structure via --steps-json."""
        task = task_store.create_task(
            project_id="summitflow",
            title="CLI Subtask Steps Test",
            task_type="task",
            priority=3,
        )
        cleanup_test_tasks.append(task["id"])

        # Use --steps-json with proper verify_command and expected_output
        steps_json = json.dumps(
            [
                {"description": "First step", "verify_command": "echo ok", "expected_output": "ok"},
                {
                    "description": "Second step",
                    "verify_command": "echo done",
                    "expected_output": "done",
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
        assert "Created subtask 1.1" in result.output

    def test_subtask_create_legacy_steps_warning(self, cleanup_test_tasks):
        """Test that using --step shows warning about missing verify_command."""
        task = task_store.create_task(
            project_id="summitflow",
            title="CLI Subtask Legacy Test",
            task_type="task",
            priority=3,
        )
        cleanup_test_tasks.append(task["id"])

        # Legacy --step flag works but warns
        result = runner.invoke(
            subtask_app,
            [
                "create",
                "1.1",
                "-d",
                "Test with legacy steps",
                "--task",
                task["id"],
                "--step",
                "First step",
                "--step",
                "Second step",
            ],
        )

        # Still creates but warns about missing verify_command
        assert "warning" in result.output.lower()
        assert "verify_command" in result.output.lower()


class TestStepCreate:
    """Test st step create command."""

    def test_step_create(self, cleanup_test_tasks):
        """Test creating steps for a subtask."""
        # Create task and subtask first
        task = task_store.create_task(
            project_id="summitflow",
            title="CLI Step Test",
            task_type="task",
            priority=3,
        )
        cleanup_test_tasks.append(task["id"])

        # Create subtask directly via storage
        from app.storage import subtasks as subtask_store

        subtask_store.create_subtask(
            task_id=task["id"],
            subtask_id="1.1",
            description="Test subtask for steps",
            phase="backend",
            display_order=0,
        )

        # Create steps via CLI (new interface: subtask_id first, --task option)
        result = runner.invoke(
            step_app,
            [
                "create",
                "1.1",
                "Step one",
                "Step two",
                "Step three",
                "--task",
                task["id"],
            ],
        )

        assert result.exit_code == 0
        assert "Created 3 steps" in result.output

    def test_step_create_invalid_task(self):
        """Test error when creating steps for non-existent task."""
        result = runner.invoke(
            step_app,
            [
                "create",
                "task-nonexistent",
                "1.1",
                "Step one",
            ],
        )

        assert result.exit_code == 1


class TestBackupCommands:
    """Test st backup commands."""

    def test_backup_list(self):
        """Test st backup list command."""
        from cli.commands.backup import app as backup_app

        result = runner.invoke(backup_app, ["list"])
        # Should succeed even with no backups
        assert result.exit_code == 0

    def test_backup_list_compact(self):
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

    def test_backup_schedule_view(self):
        """Test st backup schedule shows current config."""
        from cli.commands.backup import app as backup_app

        result = runner.invoke(backup_app, ["schedule"])
        # Should succeed even with no schedule configured
        assert result.exit_code == 0

    def test_backup_status(self):
        """Test st backup status shows latest backup."""
        from cli.commands.backup import app as backup_app

        result = runner.invoke(backup_app, ["status"])
        # Should succeed even with no backups
        assert result.exit_code == 0

    def test_backup_create_help(self):
        """Test st backup create --help."""
        from cli.commands.backup import app as backup_app

        result = runner.invoke(backup_app, ["create", "--help"])
        assert result.exit_code == 0
        assert "--note" in result.output
        assert "--keep-local" in result.output

    def test_backup_restore_help(self):
        """Test st backup restore --help."""
        from cli.commands.backup import app as backup_app

        result = runner.invoke(backup_app, ["restore", "--help"])
        assert result.exit_code == 0
        assert "--dry-run" in result.output
        assert "--yes" in result.output


class TestVerifyPlanGates:
    """Test st verify command validates step structure and final verification subtask.

    These gates ensure:
    1. Every subtask has non-empty steps array
    2. Every step has verify_command and expected_output
    3. Final subtask is a verification subtask
    """

    def test_verify_rejects_missing_steps(self):
        """st verify rejects plans with subtasks missing steps array."""
        plan = {
            "title": "Test plan with missing steps array",
            "objective": "Test objective that is long enough to pass validation",
            "task_type": "task",
            "complexity": "SIMPLE",
            "subtasks": [
                {
                    "id": "1.1",
                    "description": "Missing steps array",
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(plan, f)
            f.flush()

            result = runner.invoke(tasks_app, ["verify", f.name])

            assert result.exit_code == 1
            assert "missing required 'steps' array" in result.output.lower()

    def test_verify_rejects_empty_steps(self):
        """st verify rejects plans with empty steps array."""
        plan = {
            "title": "Test plan with empty steps array",
            "objective": "Test objective that is long enough to pass validation",
            "task_type": "task",
            "complexity": "SIMPLE",
            "subtasks": [
                {
                    "id": "1.1",
                    "description": "Empty steps array",
                    "steps": [],
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(plan, f)
            f.flush()

            result = runner.invoke(tasks_app, ["verify", f.name])

            assert result.exit_code == 1
            assert "missing required 'steps' array" in result.output.lower()

    def test_verify_rejects_steps_without_verify_command(self):
        """st verify rejects steps missing verify_command."""
        plan = {
            "title": "Test plan with steps missing verify_command",
            "objective": "Test objective that is long enough to pass validation",
            "task_type": "task",
            "complexity": "SIMPLE",
            "subtasks": [
                {
                    "id": "1.1",
                    "description": "Step without verify_command",
                    "steps": [
                        {
                            "description": "Step missing verify_command",
                            "expected_output": "Some output",
                        }
                    ],
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(plan, f)
            f.flush()

            result = runner.invoke(tasks_app, ["verify", f.name])

            assert result.exit_code == 1
            assert "missing required 'verify_command'" in result.output.lower()

    def test_verify_rejects_steps_without_expected_output(self):
        """st verify rejects steps missing expected_output."""
        plan = {
            "title": "Test plan with steps missing expected_output",
            "objective": "Test objective that is long enough to pass validation",
            "task_type": "task",
            "complexity": "SIMPLE",
            "subtasks": [
                {
                    "id": "1.1",
                    "description": "Step without expected_output",
                    "steps": [
                        {
                            "description": "Step missing expected_output",
                            "verify_command": "echo ok",
                        }
                    ],
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(plan, f)
            f.flush()

            result = runner.invoke(tasks_app, ["verify", f.name])

            assert result.exit_code == 1
            assert "missing required 'expected_output'" in result.output.lower()

    def test_verify_rejects_string_steps(self):
        """st verify rejects legacy string steps (must be objects)."""
        plan = {
            "title": "Test plan with string steps",
            "objective": "Test objective that is long enough to pass validation",
            "task_type": "task",
            "complexity": "SIMPLE",
            "subtasks": [
                {
                    "id": "1.1",
                    "description": "String steps",
                    "steps": ["Step 1 as string", "Step 2 as string"],
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(plan, f)
            f.flush()

            result = runner.invoke(tasks_app, ["verify", f.name])

            assert result.exit_code == 1
            assert "must be object with verify_command" in result.output.lower()

    def test_verify_requires_final_verification_subtask(self):
        """st verify rejects plans without a final verification subtask."""
        plan = {
            "title": "Test plan without verification subtask",
            "objective": "Test objective that is long enough to pass validation",
            "task_type": "task",
            "complexity": "SIMPLE",
            "subtasks": [
                {
                    "id": "1.1",
                    "phase": "implementation",
                    "description": "Implementation subtask",
                    "steps": [
                        {
                            "description": "Do the work",
                            "verify_command": "echo ok",
                            "expected_output": "ok",
                        }
                    ],
                }
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(plan, f)
            f.flush()

            result = runner.invoke(tasks_app, ["verify", f.name])

            assert result.exit_code == 1
            assert "must be a verification subtask" in result.output.lower()

    def test_verify_accepts_valid_plan_with_verification_subtask(self):
        """st verify accepts plan with proper steps and verification subtask."""
        plan = {
            "title": "Test plan with proper structure",
            "objective": "Test objective that is long enough to pass validation",
            "task_type": "task",
            "complexity": "SIMPLE",
            "subtasks": [
                {
                    "id": "1.1",
                    "phase": "implementation",
                    "description": "Implementation subtask",
                    "steps": [
                        {
                            "description": "Do the work",
                            "verify_command": "echo ok",
                            "expected_output": "ok",
                        }
                    ],
                },
                {
                    "id": "2.1",
                    "phase": "verification",
                    "description": "Final verification subtask",
                    "steps": [
                        {
                            "description": "Verify all is good",
                            "verify_command": "st criterion verify --all",
                            "expected_output": "All criteria verified",
                        }
                    ],
                },
            ],
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(plan, f)
            f.flush()

            result = runner.invoke(tasks_app, ["verify", f.name])

            assert result.exit_code == 0
            assert "PASS" in result.output
