"""End-to-end tests for task verification gates.

Tests the full task lifecycle through CLI commands, verifying that:
1. st verify rejects bad plans (missing steps, no verify_command, no verification subtask)
2. st import rejects bad plans with same validations
3. st subtask create rejects subtasks without proper steps
4. st subtask pass fails on subtasks with no steps or incomplete steps
5. st close fails on tasks with zero verified steps
6. Happy path: valid plan → complete steps → close task

These tests exercise the REAL CLI and API, not mocks.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

from app.storage import tasks as task_store
from app.storage.connection import get_connection

# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def project_id():
    """Ensure test project exists."""
    project_id = "summitflow"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO projects (id, name, base_url) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (project_id, "SummitFlow", "http://localhost:3001"),
        )
        conn.commit()
    return project_id


@pytest.fixture
def cleanup_tasks():
    """Track and cleanup test tasks after tests."""
    task_ids: list[str] = []
    yield task_ids
    # Cleanup - delete all test tasks
    for task_id in task_ids:
        try:
            task_store.delete_task(task_id)
        except Exception:
            pass  # Task may already be deleted


def run_cli(args: list[str], check: bool = False) -> subprocess.CompletedProcess:
    """Run st CLI command and return result."""
    result = subprocess.run(
        ["st", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, args, result.stdout, result.stderr)
    return result


def create_plan_file(plan: dict[str, Any]) -> Path:
    """Create a temporary plan.json file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        json.dump(plan, tmp)
        return Path(tmp.name)


# ============================================================================
# Test Plans - Various valid and invalid configurations
# ============================================================================


def valid_plan() -> dict[str, Any]:
    """A fully valid plan that should pass all gates."""
    return {
        "title": "E2E Test Task - Valid Plan",
        "objective": "Test that valid plans pass all verification gates",
        "task_type": "task",
        "complexity": "SIMPLE",
        "subtasks": [
            {
                "id": "1.1",
                "description": "Implementation subtask",
                "phase": "backend",
                "steps": [
                    {
                        "description": "Create test file",
                        "verify_command": "echo 'test passed'",
                        "expected_output": "test passed",
                    }
                ],
            },
            {
                "id": "1.2",
                "description": "Final verification subtask",
                "phase": "verification",
                "steps": [
                    {
                        "description": "Verify implementation complete",
                        "verify_command": "echo 'verified'",
                        "expected_output": "verified",
                    }
                ],
            },
        ],
    }


def plan_missing_steps() -> dict[str, Any]:
    """Plan with subtask missing steps array."""
    return {
        "title": "E2E Test - Missing Steps",
        "objective": "Test rejection of plans without steps",
        "task_type": "task",
        "complexity": "SIMPLE",
        "subtasks": [
            {
                "id": "1.1",
                "description": "Subtask without steps",
                "phase": "verification",
                # No steps array
            }
        ],
    }


def plan_empty_steps() -> dict[str, Any]:
    """Plan with empty steps array."""
    return {
        "title": "E2E Test - Empty Steps",
        "objective": "Test rejection of plans with empty steps",
        "task_type": "task",
        "complexity": "SIMPLE",
        "subtasks": [
            {
                "id": "1.1",
                "description": "Subtask with empty steps",
                "phase": "verification",
                "steps": [],
            }
        ],
    }


def plan_string_steps() -> dict[str, Any]:
    """Plan with legacy string steps (not objects)."""
    return {
        "title": "E2E Test - String Steps",
        "objective": "Test rejection of string steps",
        "task_type": "task",
        "complexity": "SIMPLE",
        "subtasks": [
            {
                "id": "1.1",
                "description": "Subtask with string steps",
                "phase": "verification",
                "steps": ["This is a string step"],
            }
        ],
    }


def plan_missing_verify_command() -> dict[str, Any]:
    """Plan with steps missing verify_command."""
    return {
        "title": "E2E Test - Missing verify_command",
        "objective": "Test rejection of steps without verify_command",
        "task_type": "task",
        "complexity": "SIMPLE",
        "subtasks": [
            {
                "id": "1.1",
                "description": "Subtask with incomplete steps",
                "phase": "verification",
                "steps": [
                    {
                        "description": "Step without verify_command",
                        "expected_output": "something",
                        # Missing verify_command
                    }
                ],
            }
        ],
    }


def plan_missing_expected_output() -> dict[str, Any]:
    """Plan with steps missing expected_output."""
    return {
        "title": "E2E Test - Missing expected_output",
        "objective": "Test rejection of steps without expected_output",
        "task_type": "task",
        "complexity": "SIMPLE",
        "subtasks": [
            {
                "id": "1.1",
                "description": "Subtask with incomplete steps",
                "phase": "verification",
                "steps": [
                    {
                        "description": "Step without expected_output",
                        "verify_command": "echo test",
                        # Missing expected_output
                    }
                ],
            }
        ],
    }


def plan_no_verification_subtask() -> dict[str, Any]:
    """Plan without final verification subtask."""
    return {
        "title": "E2E Test - No Verification Subtask",
        "objective": "Test rejection of plans without verification subtask",
        "task_type": "task",
        "complexity": "SIMPLE",
        "subtasks": [
            {
                "id": "1.1",
                "description": "Just an implementation subtask",
                "phase": "backend",
                "steps": [
                    {
                        "description": "Do something",
                        "verify_command": "echo ok",
                        "expected_output": "ok",
                    }
                ],
            }
        ],
    }


# ============================================================================
# Test: st verify Gate
# ============================================================================


class TestVerifyGate:
    """Test st verify command rejects invalid plans."""

    def test_verify_rejects_missing_steps(self):
        """st verify should reject plans where subtasks have no steps."""
        plan_file = create_plan_file(plan_missing_steps())
        try:
            result = run_cli(["verify", str(plan_file)])
            assert result.returncode == 1, f"Expected failure, got: {result.stdout}"
            assert "missing" in result.stderr.lower() or "steps" in result.stderr.lower()
        finally:
            plan_file.unlink()

    def test_verify_rejects_empty_steps(self):
        """st verify should reject plans with empty steps array."""
        plan_file = create_plan_file(plan_empty_steps())
        try:
            result = run_cli(["verify", str(plan_file)])
            assert result.returncode == 1, f"Expected failure, got: {result.stdout}"
            # Empty array triggers schema validation "minItems"
            assert "FAIL" in result.stdout or result.returncode == 1
        finally:
            plan_file.unlink()

    def test_verify_rejects_string_steps(self):
        """st verify should reject plans with string steps instead of objects."""
        plan_file = create_plan_file(plan_string_steps())
        try:
            result = run_cli(["verify", str(plan_file)])
            assert result.returncode == 1, f"Expected failure, got: {result.stdout}"
            assert "object" in result.stderr.lower() or "type" in result.stderr.lower()
        finally:
            plan_file.unlink()

    def test_verify_rejects_missing_verify_command(self):
        """st verify should reject steps without verify_command."""
        plan_file = create_plan_file(plan_missing_verify_command())
        try:
            result = run_cli(["verify", str(plan_file)])
            assert result.returncode == 1, f"Expected failure, got: {result.stdout}"
            assert (
                "verify_command" in result.stderr.lower()
                or "verify_command" in result.stdout.lower()
            )
        finally:
            plan_file.unlink()

    def test_verify_rejects_missing_expected_output(self):
        """st verify should reject steps without expected_output."""
        plan_file = create_plan_file(plan_missing_expected_output())
        try:
            result = run_cli(["verify", str(plan_file)])
            assert result.returncode == 1, f"Expected failure, got: {result.stdout}"
            assert (
                "expected_output" in result.stderr.lower()
                or "expected_output" in result.stdout.lower()
            )
        finally:
            plan_file.unlink()

    def test_verify_rejects_no_verification_subtask(self):
        """st verify should reject plans without final verification subtask."""
        plan_file = create_plan_file(plan_no_verification_subtask())
        try:
            result = run_cli(["verify", str(plan_file)])
            assert result.returncode == 1, f"Expected failure, got: {result.stdout}"
            assert (
                "verification" in result.stderr.lower() or "verification" in result.stdout.lower()
            )
        finally:
            plan_file.unlink()

    def test_verify_accepts_valid_plan(self):
        """st verify should accept a fully valid plan."""
        plan_file = create_plan_file(valid_plan())
        try:
            result = run_cli(["verify", str(plan_file)])
            assert result.returncode == 0, f"Expected success, got: {result.stderr}"
            assert "PASS" in result.stdout
        finally:
            plan_file.unlink()


# ============================================================================
# Test: st import Gate
# ============================================================================


class TestImportGate:
    """Test st import command rejects invalid plans."""

    def test_import_rejects_string_steps(self):
        """st import should reject plans with string steps."""
        plan_file = create_plan_file(plan_string_steps())
        try:
            result = run_cli(["import", str(plan_file), "--dry-run"])
            assert result.returncode == 1, f"Expected failure, got: {result.stdout}"
        finally:
            plan_file.unlink()

    def test_import_rejects_missing_verify_command(self):
        """st import should reject plans with missing verify_command."""
        plan_file = create_plan_file(plan_missing_verify_command())
        try:
            result = run_cli(["import", str(plan_file), "--dry-run"])
            assert result.returncode == 1, f"Expected failure, got: {result.stdout}"
        finally:
            plan_file.unlink()

    def test_import_rejects_no_verification_subtask(self):
        """st import should reject plans without verification subtask."""
        plan_file = create_plan_file(plan_no_verification_subtask())
        try:
            result = run_cli(["import", str(plan_file), "--dry-run"])
            assert result.returncode == 1, f"Expected failure, got: {result.stdout}"
        finally:
            plan_file.unlink()

    def test_import_accepts_valid_plan_dry_run(self):
        """st import --dry-run should accept a valid plan."""
        plan_file = create_plan_file(valid_plan())
        try:
            result = run_cli(["import", str(plan_file), "--dry-run"])
            assert result.returncode == 0, f"Expected success, got: {result.stderr}"
        finally:
            plan_file.unlink()


# ============================================================================
# Test: st subtask create Gate
# ============================================================================


class TestSubtaskCreateGate:
    """Test st subtask create command requires proper steps."""

    def test_subtask_create_rejects_no_steps(self, project_id, cleanup_tasks):
        """st subtask create should reject subtasks without steps."""
        # First create a task to add subtask to
        task = task_store.create_task(
            project_id=project_id,
            title="Test Task for Subtask Gate",
            description="Testing subtask creation gate",
        )
        cleanup_tasks.append(task["id"])

        # Try to create subtask without steps
        result = run_cli(
            [
                "subtask",
                "create",
                "1.1",
                "-d",
                "Subtask without steps",
                "--task",
                task["id"],
            ]
        )

        assert result.returncode == 1, f"Expected failure, got: {result.stdout}"
        assert "steps" in result.stderr.lower() or "required" in result.stderr.lower()

    def test_subtask_create_accepts_proper_steps(self, project_id, cleanup_tasks):
        """st subtask create should accept subtasks with proper steps."""
        task = task_store.create_task(
            project_id=project_id,
            title="Test Task for Subtask Gate - Valid",
            description="Testing subtask creation gate with valid steps",
        )
        cleanup_tasks.append(task["id"])

        steps_json = json.dumps(
            [
                {
                    "description": "Test step",
                    "verify_command": "echo ok",
                    "expected_output": "ok",
                }
            ]
        )

        result = run_cli(
            [
                "subtask",
                "create",
                "1.1",
                "-d",
                "Subtask with proper steps",
                "--task",
                task["id"],
                "--steps-json",
                steps_json,
            ]
        )

        assert result.returncode == 0, f"Expected success, got: {result.stderr}"


# ============================================================================
# Test: st subtask pass Gate
# ============================================================================


class TestSubtaskPassGate:
    """Test st subtask pass command requires completed steps."""

    def test_subtask_pass_fails_without_steps(self, project_id, cleanup_tasks):
        """st subtask pass should fail if subtask has no steps."""
        # Create task
        task = task_store.create_task(
            project_id=project_id,
            title="Test Task for Pass Gate - No Steps",
            description="Testing pass gate on subtask without steps",
        )
        cleanup_tasks.append(task["id"])

        # Create subtask without steps via storage layer (bypassing CLI gate)
        from app.storage import subtasks as subtask_store

        subtask_store.create_subtask(
            task_id=task["id"],
            subtask_id="1.1",
            description="Subtask without steps",
            display_order=0,
            steps=[],  # Empty steps
        )

        # Try to pass subtask (note: subtask_id is positional, --task is option)
        result = run_cli(
            [
                "subtask",
                "pass",
                "1.1",
                "--task",
                task["id"],
            ]
        )

        assert result.returncode == 1, f"Expected failure, got: {result.stdout}"
        assert "no steps" in result.stderr.lower() or "gate" in result.stderr.lower()

    def test_subtask_pass_fails_with_incomplete_steps(self, project_id, cleanup_tasks):
        """st subtask pass should fail if steps are not completed."""
        task = task_store.create_task(
            project_id=project_id,
            title="Test Task for Pass Gate - Incomplete Steps",
            description="Testing pass gate on subtask with incomplete steps",
        )
        cleanup_tasks.append(task["id"])

        from app.storage import subtasks as subtask_store

        subtask_store.create_subtask(
            task_id=task["id"],
            subtask_id="1.1",
            description="Subtask with incomplete steps",
            display_order=0,
            steps=[
                {"description": "Step 1", "verify_command": "echo 1", "expected_output": "1"},
                {"description": "Step 2", "verify_command": "echo 2", "expected_output": "2"},
            ],
        )

        # Try to pass subtask without completing steps
        result = run_cli(
            [
                "subtask",
                "pass",
                "1.1",
                "--task",
                task["id"],
            ]
        )

        assert result.returncode == 1, f"Expected failure, got: {result.stdout}"
        assert "not complete" in result.stderr.lower() or "incomplete" in result.stderr.lower()


# ============================================================================
# Test: st close Gate
# ============================================================================


class TestCloseGate:
    """Test st close command requires verified steps."""

    def test_close_fails_with_zero_steps(self, project_id, cleanup_tasks):
        """st close should fail if task has zero steps (after QA gate)."""
        task = task_store.create_task(
            project_id=project_id,
            title="Test Task for Close Gate - Zero Steps",
            description="Testing close gate on task with no steps",
        )
        cleanup_tasks.append(task["id"])

        # Approve plan, update to running, skip QA (to test step gate)
        run_cli(["approve", task["id"]])
        run_cli(["update", task["id"], "--status", "running"])
        run_cli(["qa", "skip", task["id"]])  # Skip QA to test step gate

        # Try to close - should fail due to zero steps
        result = run_cli(
            [
                "close",
                task["id"],
                "--reason",
                "Testing close gate",
            ]
        )

        assert result.returncode == 1, f"Expected failure, got: {result.stdout}"
        # Error message is in stdout as JSON, not stderr
        output = (result.stdout + result.stderr).lower()
        assert "zero" in output or "step" in output, f"Expected zero/step error, got: {output}"

    def test_close_fails_with_incomplete_subtasks(self, project_id, cleanup_tasks):
        """st close should fail if subtasks are not completed."""
        task = task_store.create_task(
            project_id=project_id,
            title="Test Task for Close Gate - Incomplete Subtasks",
            description="Testing close gate with incomplete subtasks",
        )
        cleanup_tasks.append(task["id"])

        from app.storage import subtasks as subtask_store

        subtask_store.create_subtask(
            task_id=task["id"],
            subtask_id="1.1",
            description="Incomplete subtask",
            display_order=0,
            steps=[
                {"description": "Step 1", "verify_command": "echo 1", "expected_output": "1"},
            ],
        )

        # Approve plan, update to running, skip QA
        run_cli(["approve", task["id"]])
        run_cli(["update", task["id"], "--status", "running"])
        run_cli(["qa", "skip", task["id"]])

        # Try to close without completing subtask
        result = run_cli(
            [
                "close",
                task["id"],
                "--reason",
                "Testing close gate",
            ]
        )

        assert result.returncode == 1, f"Expected failure, got: {result.stdout}"
        # Error message is in stdout as JSON, not stderr
        output = (result.stdout + result.stderr).lower()
        assert "incomplete" in output or "subtask" in output, (
            f"Expected incomplete/subtask error, got: {output}"
        )


# ============================================================================
# Test: Happy Path - Full Lifecycle
# ============================================================================


class TestHappyPath:
    """Test the complete happy path: import → execute → close."""

    def test_full_lifecycle_via_import(self, project_id, cleanup_tasks):
        """Test complete task lifecycle: import valid plan → complete steps → close."""
        # 1. Create and import valid plan
        plan_file = create_plan_file(valid_plan())
        try:
            result = run_cli(["import", str(plan_file)])
            assert result.returncode == 0, f"Import failed: {result.stderr}"

            # Extract task ID from output (format: "Created task: task-xxxxxxxx")
            import re

            match = re.search(r"task-[a-f0-9]+", result.stdout)
            assert match, f"Could not find task ID in output: {result.stdout}"
            task_id = match.group(0)
            cleanup_tasks.append(task_id)
        finally:
            plan_file.unlink()

        # 2. Verify task was created with subtasks
        result = run_cli(["subtask", "list", task_id])
        assert result.returncode == 0
        assert "1.1" in result.stdout
        assert "1.2" in result.stdout

        # 3. Approve plan then update task to running
        result = run_cli(["approve", task_id])
        assert result.returncode == 0, f"Approve failed: {result.stderr}"

        result = run_cli(["update", task_id, "--status", "running"])
        assert result.returncode == 0, f"Update to running failed: {result.stderr}"

        # 4. Complete steps for each subtask
        for subtask_id in ["1.1", "1.2"]:
            # Pass step 1 (each subtask has 1 step)
            # Format: st step pass <subtask_id> <step_number> --task <task_id>
            result = run_cli(["step", "pass", subtask_id, "1", "--task", task_id])
            assert result.returncode == 0, f"Step pass failed for {subtask_id}: {result.stderr}"

            # Pass subtask
            # Format: st subtask pass <subtask_id> --task <task_id>
            result = run_cli(["subtask", "pass", subtask_id, "--task", task_id])
            assert result.returncode == 0, f"Subtask pass failed for {subtask_id}: {result.stderr}"

        # 5. QA pass (or skip for SIMPLE tasks)
        result = run_cli(["qa", "skip", task_id])
        assert result.returncode == 0, f"QA skip failed: {result.stderr}"

        # 6. Close task
        result = run_cli(["close", task_id, "--reason", "E2E test complete"])
        assert result.returncode == 0, f"Close failed: {result.stderr}"

        # 7. Verify final state
        result = run_cli(["show", task_id])
        assert "completed" in result.stdout.lower()

    def test_gate_sequence_prevents_shortcuts(self, project_id, cleanup_tasks):
        """Test that you cannot skip gates in the lifecycle."""
        # Create task
        task = task_store.create_task(
            project_id=project_id,
            title="Test Gate Sequence",
            description="Testing that gates cannot be bypassed",
        )
        cleanup_tasks.append(task["id"])

        from app.storage import subtasks as subtask_store

        # Create subtask with steps
        subtask_store.create_subtask(
            task_id=task["id"],
            subtask_id="1.1",
            description="Test subtask",
            display_order=0,
            steps=[
                {"description": "Step 1", "verify_command": "echo 1", "expected_output": "1"},
            ],
        )

        # Approve plan and update to running
        run_cli(["approve", task["id"]])
        run_cli(["update", task["id"], "--status", "running"])

        # Try to close without QA - should fail (QA gate comes first)
        result = run_cli(["close", task["id"], "--reason", "Shortcut attempt"])
        assert result.returncode == 1, "Should not be able to close without QA"

        # Skip QA to test subtask gate
        run_cli(["qa", "skip", task["id"]])

        # Try to close without completing subtasks - should fail
        result = run_cli(["close", task["id"], "--reason", "Shortcut attempt"])
        assert result.returncode == 1, "Should not be able to close with incomplete subtasks"

        # Try to pass subtask without completing steps - should fail
        result = run_cli(["subtask", "pass", "1.1", "--task", task["id"]])
        assert result.returncode == 1, "Should not be able to pass subtask with incomplete steps"

        # Now do it properly: pass step → pass subtask → close
        result = run_cli(["step", "pass", "1.1", "1", "--task", task["id"]])
        assert result.returncode == 0, f"Step pass failed: {result.stderr}"

        result = run_cli(["subtask", "pass", "1.1", "--task", task["id"]])
        assert result.returncode == 0, f"Subtask pass failed: {result.stderr}"

        result = run_cli(["close", task["id"], "--reason", "Proper completion"])
        assert result.returncode == 0, f"Close failed: {result.stderr}"


# ============================================================================
# Run tests directly
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x"])
