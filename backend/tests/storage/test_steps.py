"""Unit tests for steps storage layer."""

from unittest.mock import patch

import pytest

from app.storage import steps as step_store
from app.storage import subtasks as subtask_store
from app.storage import tasks as task_store
from app.storage.connection import get_connection
from app.storage.steps import StepVerificationError


@pytest.fixture
def project_id():
    """Ensure test project exists."""
    project_id = "test-project"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO projects (id, name, base_url) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (project_id, "SummitFlow", "http://localhost:3001"),
        )
        conn.commit()
    return project_id


@pytest.fixture
def test_task(project_id):
    """Create and cleanup a test task for step tests."""
    task = task_store.create_task(
        project_id=project_id,
        title="Test Task for Steps",
        description="Created by test fixture",
    )

    yield task

    # Cleanup task (cascades to subtasks and steps)
    task_store.delete_task(task["id"])


@pytest.fixture
def test_subtask(test_task):
    """Create and cleanup a test subtask for step tests."""
    subtask = subtask_store.create_subtask(
        task_id=test_task["id"],
        subtask_id="1.1",
        description="Test subtask for steps",
        display_order=0,
        phase="test",
    )

    yield subtask

    # Cleanup happens via task cascade


class TestCreateStep:
    """Tests for create_step function."""

    def test_create_step_basic(self, test_subtask):
        """Test creating a basic step."""
        step = step_store.create_step(
            subtask_id=test_subtask["id"],
            step_number=1,
            description="First test step",
        )

        assert step is not None
        assert step["subtask_id"] == test_subtask["id"]
        assert step["step_number"] == 1
        assert step["description"] == "First test step"
        assert step["passes"] is False
        assert step["passed_at"] is None
        assert step["created_at"] is not None

    def test_create_step_multiple(self, test_subtask):
        """Test creating multiple steps with sequential numbers."""
        step1 = step_store.create_step(test_subtask["id"], 1, "Step one")
        step2 = step_store.create_step(test_subtask["id"], 2, "Step two")
        step3 = step_store.create_step(test_subtask["id"], 3, "Step three")

        assert step1["step_number"] == 1
        assert step2["step_number"] == 2
        assert step3["step_number"] == 3


class TestGetStepsForSubtask:
    """Tests for get_steps_for_subtask function."""

    def test_get_steps_empty(self, test_subtask):
        """Test getting steps from subtask with no steps."""
        steps = step_store.get_steps_for_subtask(test_subtask["id"])

        assert steps == []

    def test_get_steps_populated(self, test_subtask):
        """Test getting steps from subtask with steps."""
        step_store.create_step(test_subtask["id"], 1, "First step")
        step_store.create_step(test_subtask["id"], 2, "Second step")

        steps = step_store.get_steps_for_subtask(test_subtask["id"])

        assert len(steps) == 2
        assert steps[0]["step_number"] == 1
        assert steps[1]["step_number"] == 2

    def test_get_steps_ordered(self, test_subtask):
        """Test that steps are returned in order by step_number."""
        # Create out of order
        step_store.create_step(test_subtask["id"], 3, "Third")
        step_store.create_step(test_subtask["id"], 1, "First")
        step_store.create_step(test_subtask["id"], 2, "Second")

        steps = step_store.get_steps_for_subtask(test_subtask["id"])

        assert len(steps) == 3
        assert [s["step_number"] for s in steps] == [1, 2, 3]

    def test_get_steps_nonexistent_subtask(self):
        """Test getting steps for non-existent subtask returns empty list."""
        steps = step_store.get_steps_for_subtask("nonexistent-subtask-id")

        assert steps == []


class TestUpdateStepPasses:
    """Tests for update_step_passes function.

    Note: Steps now require verify_command for passes=True.
    We mock run_verify_command to control verification outcomes.
    """

    @patch("app.storage.steps_updates.run_verify_command")
    def test_update_step_passes_true(self, mock_verify, test_subtask):
        """Test marking a step as passing with successful verification."""
        mock_verify.return_value = ("passed", 0, "ok")
        step_store.create_step(
            test_subtask["id"], 1, "Test step", verify_command="echo pass", expected_output="ok"
        )

        updated = step_store.update_step_passes(test_subtask["id"], 1, True)

        assert updated is not None
        assert updated["passes"] is True
        assert updated["passed_at"] is not None
        mock_verify.assert_called_once_with("echo pass", cwd=None, project_id=None)

    @patch("app.storage.steps_updates.run_verify_command")
    def test_update_step_passes_false(self, mock_verify, test_subtask):
        """Test marking a step as not passing (resetting)."""
        mock_verify.return_value = ("passed", 0, "ok")
        step_store.create_step(
            test_subtask["id"], 1, "Test step", verify_command="echo pass", expected_output="ok"
        )
        step_store.update_step_passes(test_subtask["id"], 1, True)

        # passes=False doesn't run verification
        updated = step_store.update_step_passes(test_subtask["id"], 1, False)

        assert updated is not None
        assert updated["passes"] is False
        assert updated["passed_at"] is None

    @patch("app.storage.steps_updates.run_verify_command")
    def test_update_step_passes_toggle(self, mock_verify, test_subtask):
        """Test toggling step pass status multiple times."""
        mock_verify.return_value = ("passed", 0, "ok")
        step_store.create_step(
            test_subtask["id"], 1, "Test step", verify_command="echo pass", expected_output="ok"
        )

        # Toggle on
        updated1 = step_store.update_step_passes(test_subtask["id"], 1, True)
        assert updated1["passes"] is True

        # Toggle off
        updated2 = step_store.update_step_passes(test_subtask["id"], 1, False)
        assert updated2["passes"] is False

        # Toggle on again
        updated3 = step_store.update_step_passes(test_subtask["id"], 1, True)
        assert updated3["passes"] is True

    def test_update_step_passes_nonexistent(self, test_subtask):
        """Test updating non-existent step returns None."""
        result = step_store.update_step_passes(test_subtask["id"], 999, True)

        assert result is None

    def test_update_step_passes_no_verify_command_raises(self, test_subtask):
        """Test that passes=True without verify_command raises error."""
        step_store.create_step(test_subtask["id"], 1, "Test step")  # No verify_command

        with pytest.raises(StepVerificationError, match="no verify_command"):
            step_store.update_step_passes(test_subtask["id"], 1, True)

    @patch("app.storage.steps_updates.run_verify_command")
    def test_update_step_passes_verification_fails(self, mock_verify, test_subtask):
        """Test that verification failure raises error."""
        mock_verify.return_value = ("failed", 1, "error output")
        step_store.create_step(
            test_subtask["id"], 1, "Test step", verify_command="exit 1", expected_output="ok"
        )

        with pytest.raises(StepVerificationError, match="verification failed"):
            step_store.update_step_passes(test_subtask["id"], 1, True)

    @patch("app.storage.steps_updates.run_verify_command")
    def test_already_verified_skips_verify_command(self, mock_verify, test_subtask):
        """Test that already_verified=True skips running verify_command."""
        step_store.create_step(
            test_subtask["id"], 1, "Test step", verify_command="echo pass", expected_output="ok"
        )

        updated = step_store.update_step_passes(
            test_subtask["id"], 1, True, already_verified=True
        )

        assert updated is not None
        assert updated["passes"] is True
        assert updated["passed_at"] is not None
        mock_verify.assert_not_called()

    @patch("app.storage.steps_updates.run_verify_command")
    def test_already_verified_false_still_runs_verification(self, mock_verify, test_subtask):
        """Test that already_verified=False (default) still runs verify_command."""
        mock_verify.return_value = ("passed", 0, "ok")
        step_store.create_step(
            test_subtask["id"], 1, "Test step", verify_command="echo pass", expected_output="ok"
        )

        updated = step_store.update_step_passes(
            test_subtask["id"], 1, True, already_verified=False
        )

        assert updated is not None
        assert updated["passes"] is True
        mock_verify.assert_called_once()


class TestBulkCreateSteps:
    """Tests for bulk_create_steps function."""

    def test_bulk_create_steps_basic(self, test_subtask):
        """Test bulk creating multiple steps."""
        descriptions = ["Step 1", "Step 2", "Step 3"]

        created = step_store.bulk_create_steps(test_subtask["id"], descriptions)

        assert len(created) == 3
        assert created[0]["step_number"] == 1
        assert created[1]["step_number"] == 2
        assert created[2]["step_number"] == 3
        assert created[0]["description"] == "Step 1"

    def test_bulk_create_steps_empty(self, test_subtask):
        """Test bulk creating with empty list."""
        created = step_store.bulk_create_steps(test_subtask["id"], [])

        assert created == []

    def test_bulk_create_steps_single(self, test_subtask):
        """Test bulk creating single step."""
        created = step_store.bulk_create_steps(test_subtask["id"], ["Only step"])

        assert len(created) == 1
        assert created[0]["step_number"] == 1
        assert created[0]["description"] == "Only step"


class TestDeleteStepsForSubtask:
    """Tests for delete_steps_for_subtask function."""

    def test_delete_steps_basic(self, test_subtask):
        """Test deleting all steps for a subtask."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2", "Step 3"])

        count = step_store.delete_steps_for_subtask(test_subtask["id"])

        assert count == 3

        # Verify deletion
        steps = step_store.get_steps_for_subtask(test_subtask["id"])
        assert steps == []

    def test_delete_steps_empty(self, test_subtask):
        """Test deleting from subtask with no steps."""
        count = step_store.delete_steps_for_subtask(test_subtask["id"])

        assert count == 0

    def test_delete_steps_nonexistent_subtask(self):
        """Test deleting steps for non-existent subtask."""
        count = step_store.delete_steps_for_subtask("nonexistent-subtask")

        assert count == 0


class TestGetStepSummary:
    """Tests for get_step_summary function."""

    def test_step_summary_empty(self, test_subtask):
        """Test summary with no steps."""
        summary = step_store.get_step_summary(test_subtask["id"])

        assert summary["total"] == 0
        assert summary["completed"] == 0
        assert summary["progress_percent"] == 0

    def test_step_summary_all_incomplete(self, test_subtask):
        """Test summary with all steps incomplete."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2", "Step 3"])

        summary = step_store.get_step_summary(test_subtask["id"])

        assert summary["total"] == 3
        assert summary["completed"] == 0
        assert summary["progress_percent"] == 0

    @patch("app.storage.steps_updates.run_verify_command")
    def test_step_summary_partial(self, mock_verify, test_subtask):
        """Test summary with partial completion."""
        mock_verify.return_value = ("passed", 0, "ok")
        steps = [
            {"description": "Step 1", "verify_command": "echo 1", "expected_output": "ok"},
            {"description": "Step 2", "verify_command": "echo 2", "expected_output": "ok"},
            {"description": "Step 3", "verify_command": "echo 3", "expected_output": "ok"},
            {"description": "Step 4", "verify_command": "echo 4", "expected_output": "ok"},
        ]
        step_store.bulk_create_steps(test_subtask["id"], steps)
        step_store.update_step_passes(test_subtask["id"], 1, True)
        step_store.update_step_passes(test_subtask["id"], 2, True)

        summary = step_store.get_step_summary(test_subtask["id"])

        assert summary["total"] == 4
        assert summary["completed"] == 2
        assert summary["progress_percent"] == 50.0

    @patch("app.storage.steps_updates.run_verify_command")
    def test_step_summary_all_complete(self, mock_verify, test_subtask):
        """Test summary with all steps complete."""
        mock_verify.return_value = ("passed", 0, "ok")
        steps = [
            {"description": "Step 1", "verify_command": "echo 1", "expected_output": "ok"},
            {"description": "Step 2", "verify_command": "echo 2", "expected_output": "ok"},
        ]
        step_store.bulk_create_steps(test_subtask["id"], steps)
        step_store.update_step_passes(test_subtask["id"], 1, True)
        step_store.update_step_passes(test_subtask["id"], 2, True)

        summary = step_store.get_step_summary(test_subtask["id"])

        assert summary["total"] == 2
        assert summary["completed"] == 2
        assert summary["progress_percent"] == 100.0

    def test_step_summary_nonexistent_subtask(self):
        """Test summary for non-existent subtask."""
        summary = step_store.get_step_summary("nonexistent-subtask")

        assert summary["total"] == 0
        assert summary["completed"] == 0
        assert summary["progress_percent"] == 0


class TestStepGates:
    """Tests for step sequential completion gate.

    Note: Steps require verify_command. Out-of-order completion logs info.
    Force param has been removed - no bypass allowed.
    """

    @patch("app.storage.steps_updates.run_verify_command")
    def test_step_gate_allows_out_of_order_completion(self, mock_verify, test_subtask):
        """Can mark step 2 as passed even if step 1 is not passed (logs info)."""
        mock_verify.return_value = ("passed", 0, "ok")
        steps = [
            {"description": "Step 1", "verify_command": "echo 1", "expected_output": "ok"},
            {"description": "Step 2", "verify_command": "echo 2", "expected_output": "ok"},
            {"description": "Step 3", "verify_command": "echo 3", "expected_output": "ok"},
        ]
        step_store.bulk_create_steps(test_subtask["id"], steps)

        result = step_store.update_step_passes(test_subtask["id"], step_number=2, passes=True)
        assert result["passes"] is True

    @patch("app.storage.steps_updates.run_verify_command")
    def test_step_gate_allows_sequential_completion(self, mock_verify, test_subtask):
        """Can mark step 2 as passed after step 1 is passed."""
        mock_verify.return_value = ("passed", 0, "ok")
        steps = [
            {"description": "Step 1", "verify_command": "echo 1", "expected_output": "ok"},
            {"description": "Step 2", "verify_command": "echo 2", "expected_output": "ok"},
            {"description": "Step 3", "verify_command": "echo 3", "expected_output": "ok"},
        ]
        step_store.bulk_create_steps(test_subtask["id"], steps)

        # Mark step 1 as passed
        result1 = step_store.update_step_passes(test_subtask["id"], step_number=1, passes=True)
        assert result1["passes"] is True

        # Now step 2 should work
        result2 = step_store.update_step_passes(test_subtask["id"], step_number=2, passes=True)
        assert result2["passes"] is True

    def test_step_gate_force_param_removed(self, test_subtask):
        """Force flag has been removed - no bypass available."""
        steps = [
            {"description": "Step 1", "verify_command": "echo 1", "expected_output": "ok"},
            {"description": "Step 2", "verify_command": "echo 2", "expected_output": "ok"},
        ]
        step_store.bulk_create_steps(test_subtask["id"], steps)

        # force=True should raise TypeError
        with pytest.raises(TypeError, match="unexpected keyword argument 'force'"):
            step_store.update_step_passes(
                test_subtask["id"], step_number=2, passes=True, force=True
            )

    @patch("app.storage.steps_updates.run_verify_command")
    def test_step_gate_first_step_no_check(self, mock_verify, test_subtask):
        """First step has no gate check (no previous steps)."""
        mock_verify.return_value = ("passed", 0, "ok")
        steps = [
            {"description": "Step 1", "verify_command": "echo 1", "expected_output": "ok"},
            {"description": "Step 2", "verify_command": "echo 2", "expected_output": "ok"},
        ]
        step_store.bulk_create_steps(test_subtask["id"], steps)

        # Step 1 should always work
        result = step_store.update_step_passes(test_subtask["id"], step_number=1, passes=True)
        assert result["passes"] is True

    @patch("app.storage.steps_updates.run_verify_command")
    def test_step_gate_logs_missing_steps(self, mock_verify, test_subtask):
        """Gate logs missing steps but allows completion with valid verify_command."""
        mock_verify.return_value = ("passed", 0, "ok")
        steps = [
            {"description": "Step 1", "verify_command": "echo 1", "expected_output": "ok"},
            {"description": "Step 2", "verify_command": "echo 2", "expected_output": "ok"},
            {"description": "Step 3", "verify_command": "echo 3", "expected_output": "ok"},
        ]
        step_store.bulk_create_steps(test_subtask["id"], steps)

        result = step_store.update_step_passes(test_subtask["id"], step_number=3, passes=True)
        assert result["passes"] is True

    def test_clearing_step_has_no_gate(self, test_subtask):
        """Setting passes=False has no gate check (can clear any step)."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2"])

        # Can clear step 2 even if step 1 is not passed (no verify_command needed for False)
        result = step_store.update_step_passes(test_subtask["id"], step_number=2, passes=False)
        assert result["passes"] is False


class TestInsertStep:
    """Tests for insert_step function."""

    def test_insert_step_at_beginning(self, test_subtask):
        """Insert at position 1 shifts all existing steps."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2"])

        inserted = step_store.insert_step(test_subtask["id"], 1, "New First Step")

        assert inserted["step_number"] == 1
        assert inserted["description"] == "New First Step"

        steps = step_store.get_steps_for_subtask(test_subtask["id"])
        assert len(steps) == 3
        assert steps[0]["description"] == "New First Step"
        assert steps[1]["description"] == "Step 1"
        assert steps[1]["step_number"] == 2
        assert steps[2]["description"] == "Step 2"
        assert steps[2]["step_number"] == 3

    def test_insert_step_in_middle(self, test_subtask):
        """Insert in middle shifts only steps at and after position."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2", "Step 3"])

        inserted = step_store.insert_step(test_subtask["id"], 2, "New Middle Step")

        assert inserted["step_number"] == 2

        steps = step_store.get_steps_for_subtask(test_subtask["id"])
        assert len(steps) == 4
        assert steps[0]["description"] == "Step 1"
        assert steps[0]["step_number"] == 1
        assert steps[1]["description"] == "New Middle Step"
        assert steps[1]["step_number"] == 2
        assert steps[2]["description"] == "Step 2"
        assert steps[2]["step_number"] == 3
        assert steps[3]["description"] == "Step 3"
        assert steps[3]["step_number"] == 4

    def test_insert_step_at_end(self, test_subtask):
        """Insert at position after last step acts like append."""
        step_store.bulk_create_steps(test_subtask["id"], ["Step 1", "Step 2"])

        inserted = step_store.insert_step(test_subtask["id"], 3, "Step 3")

        assert inserted["step_number"] == 3

        steps = step_store.get_steps_for_subtask(test_subtask["id"])
        assert len(steps) == 3
        assert steps[2]["description"] == "Step 3"

    def test_insert_step_empty_subtask(self, test_subtask):
        """Insert into empty subtask works."""
        inserted = step_store.insert_step(test_subtask["id"], 1, "First Step")

        assert inserted["step_number"] == 1

        steps = step_store.get_steps_for_subtask(test_subtask["id"])
        assert len(steps) == 1

    def test_insert_step_invalid_position(self, test_subtask):
        """Position < 1 raises ValueError."""
        with pytest.raises(ValueError, match="Position must be >= 1"):
            step_store.insert_step(test_subtask["id"], 0, "Invalid")


class TestSanitizeVerifyCommand:
    """Tests for _sanitize_verify_command absolute path rejection."""

    def test_sanitize_none_passes_through(self):
        from app.storage.steps_crud import _sanitize_verify_command

        assert _sanitize_verify_command(None) is None

    def test_sanitize_empty_passes_through(self):
        from app.storage.steps_crud import _sanitize_verify_command

        assert _sanitize_verify_command("") == ""

    def test_sanitize_relative_command_passes(self):
        from app.storage.steps_crud import _sanitize_verify_command

        cmd = "rg 'pattern' backend/app/main.py"
        assert _sanitize_verify_command(cmd) == cmd

    def test_sanitize_rejects_cd_absolute_path(self):
        from app.storage.steps_crud import _sanitize_verify_command

        with pytest.raises(ValueError, match="absolute path"):
            _sanitize_verify_command("cd /home/user/project && grep foo bar.py")

    def test_sanitize_rejects_absolute_home_path(self):
        from app.storage.steps_crud import _sanitize_verify_command

        with pytest.raises(ValueError, match="absolute path"):
            _sanitize_verify_command("cat /home/user/project/file.txt")

    def test_sanitize_rejects_absolute_tmp_path(self):
        from app.storage.steps_crud import _sanitize_verify_command

        with pytest.raises(ValueError, match="absolute path"):
            _sanitize_verify_command("ls /tmp/test-output")

    def test_sanitize_rejects_absolute_opt_path(self):
        from app.storage.steps_crud import _sanitize_verify_command

        with pytest.raises(ValueError, match="absolute path"):
            _sanitize_verify_command("test -f /opt/app/config.yaml")

    @pytest.mark.parametrize(
        "cmd",
        [
            "echo hello",
            "rg pattern src/",
            "test -f backend/app/main.py",
            "pytest tests/",
            "dt --quick --changed-only",
        ],
    )
    def test_sanitize_allows_relative_commands(self, cmd):
        from app.storage.steps_crud import _sanitize_verify_command

        assert _sanitize_verify_command(cmd) == cmd

    def test_create_step_raises_on_absolute_path(self, test_subtask):
        """Integration: create_step propagates ValueError from sanitizer."""
        with pytest.raises(ValueError, match="absolute path"):
            step_store.create_step(
                test_subtask["id"],
                1,
                "Bad step",
                verify_command="cd /home/user/project && echo test",
            )

    def test_bulk_create_raises_on_absolute_path(self, test_subtask):
        """Integration: bulk_create_steps propagates ValueError from sanitizer."""
        steps = [
            {"description": "Bad step", "verify_command": "cat /home/user/file.txt", "expected_output": "content"},
        ]
        with pytest.raises(ValueError, match="absolute path"):
            step_store.bulk_create_steps(test_subtask["id"], steps)
