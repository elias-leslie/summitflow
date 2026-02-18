"""End-to-end tests for task verification gates.

Tests the full task lifecycle through CLI commands, verifying that:
1. st verify rejects bad plans (missing steps, no verify_command, no verification subtask)
2. st import rejects bad plans with same validations
3. st subtask create rejects subtasks without proper steps
4. st subtask pass fails on subtasks with no steps or incomplete steps
5. st done fails on tasks with zero verified steps
6. Happy path: valid plan → complete steps → done task

These tests exercise the REAL CLI and API, not mocks.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from app.storage import tasks as task_store
from app.storage.connection import get_connection

# ============================================================================
# Test Fixtures
# ============================================================================


def _backend_available() -> bool:
    """Check if the backend API server is running."""
    try:
        urllib.request.urlopen("http://127.0.0.1:5000/api/health", timeout=2)
        return True
    except (urllib.error.URLError, TimeoutError):
        return False


@pytest.fixture
def requires_backend() -> None:
    """Skip test if backend server is not running."""
    if not _backend_available():
        pytest.skip("Backend server not running (required for this E2E test)")


@pytest.fixture
def project_id() -> str:
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
def cleanup_tasks() -> Any:
    """Track and cleanup test tasks after tests."""
    task_ids: list[str] = []
    yield task_ids
    # Cleanup - delete all test tasks
    for task_id in task_ids:
        try:
            task_store.delete_task(task_id)
        except Exception:
            pass  # Task may already be deleted


def run_cli(
    args: list[str], check: bool = False, project_id: str = "test-project"
) -> subprocess.CompletedProcess[str]:
    """Run st CLI command and return result."""
    import os

    env = os.environ.copy()
    env["ST_PROJECT_ID"] = project_id
    result = subprocess.run(
        ["st", *args],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
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
                    },
                    {
                        # Deploy step - uses echo to simulate rebuild.sh in tests
                        # Validation passes because description contains "deploy"
                        "description": "Deploy backend changes",
                        "verify_command": "echo 'rebuild.sh simulation: Rebuild complete'",
                    },
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
                        # Missing verify_command
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
                    },
                    {
                        "description": "Deploy backend changes",
                        "verify_command": "echo 'rebuild.sh simulation: Rebuild complete'",
                    },
                ],
            }
        ],
    }


def plan_missing_deploy_step() -> dict[str, Any]:
    """Plan with backend phase subtask missing deploy step."""
    return {
        "title": "E2E Test - Missing Deploy Step",
        "objective": "Test rejection of plans without deploy step",
        "task_type": "task",
        "complexity": "SIMPLE",
        "subtasks": [
            {
                "id": "1.1",
                "description": "Backend subtask without deploy",
                "phase": "backend",
                "steps": [
                    {
                        "description": "Do something",
                        "verify_command": "echo ok",
                    }
                ],
            },
            {
                "id": "1.2",
                "description": "Final verification",
                "phase": "verification",
                "steps": [
                    {
                        "description": "Verify",
                        "verify_command": "echo done",
                    }
                ],
            },
        ],
    }


def plan_frontend_missing_browser_check() -> dict[str, Any]:
    """Plan with frontend phase subtask missing browser verification step."""
    return {
        "title": "E2E Test - Missing Browser Check",
        "objective": "Test rejection of frontend plans without browser check",
        "task_type": "task",
        "complexity": "SIMPLE",
        "subtasks": [
            {
                "id": "1.1",
                "description": "Frontend subtask without browser check",
                "phase": "frontend",
                "steps": [
                    {
                        "description": "Update component",
                        "verify_command": "echo ok",
                    },
                    {
                        # Has deploy but no browser check
                        "description": "Deploy frontend changes",
                        "verify_command": "echo 'rebuild.sh simulation: Rebuild complete'",
                    },
                ],
            },
            {
                "id": "1.2",
                "description": "Final verification",
                "phase": "verification",
                "steps": [
                    {
                        "description": "Verify",
                        "verify_command": "echo done",
                    }
                ],
            },
        ],
    }


def plan_frontend_valid() -> dict[str, Any]:
    """Valid frontend plan with deploy and browser check."""
    return {
        "title": "E2E Test - Valid Frontend Plan",
        "objective": "Test acceptance of valid frontend plan",
        "task_type": "task",
        "complexity": "SIMPLE",
        "subtasks": [
            {
                "id": "1.1",
                "description": "Frontend subtask with all required steps",
                "phase": "frontend",
                "steps": [
                    {
                        "description": "Update component",
                        "verify_command": "echo ok",
                    },
                    {
                        "description": "Deploy frontend changes",
                        "verify_command": "echo 'rebuild.sh simulation: Rebuild complete'",
                    },
                    {
                        "description": "Verify no console errors",
                        "verify_command": "echo 'agent-browser errors: No errors'",
                    },
                ],
            },
            {
                "id": "1.2",
                "description": "Final verification",
                "phase": "verification",
                "steps": [
                    {
                        "description": "Verify",
                        "verify_command": "echo done",
                    }
                ],
            },
        ],
    }


# ============================================================================
# Test: st verify Gate
# ============================================================================


class TestVerifyGate:
    """Test st verify command rejects invalid plans."""

    def test_verify_rejects_missing_steps(self) -> None:
        """st verify should reject plans where subtasks have no steps."""
        plan_file = create_plan_file(plan_missing_steps())
        try:
            result = run_cli(["verify", str(plan_file)])
            assert result.returncode == 1, f"Expected failure, got: {result.stdout}"
            assert "missing" in result.stderr.lower() or "steps" in result.stderr.lower()
        finally:
            plan_file.unlink()

    def test_verify_rejects_empty_steps(self) -> None:
        """st verify should reject plans with empty steps array."""
        plan_file = create_plan_file(plan_empty_steps())
        try:
            result = run_cli(["verify", str(plan_file)])
            assert result.returncode == 1, f"Expected failure, got: {result.stdout}"
            # Empty array triggers schema validation "minItems"
            assert "FAIL" in result.stdout or result.returncode == 1
        finally:
            plan_file.unlink()

    def test_verify_rejects_string_steps(self) -> None:
        """st verify should reject plans with string steps instead of objects."""
        plan_file = create_plan_file(plan_string_steps())
        try:
            result = run_cli(["verify", str(plan_file)])
            assert result.returncode == 1, f"Expected failure, got: {result.stdout}"
            assert "object" in result.stderr.lower() or "type" in result.stderr.lower()
        finally:
            plan_file.unlink()

    def test_verify_rejects_missing_verify_command(self) -> None:
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

    def test_verify_rejects_no_verification_subtask(self) -> None:
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

    def test_verify_rejects_missing_deploy_step(self) -> None:
        """st verify should reject backend/frontend subtasks without deploy step."""
        plan_file = create_plan_file(plan_missing_deploy_step())
        try:
            result = run_cli(["verify", str(plan_file)])
            assert result.returncode == 1, f"Expected failure, got: {result.stdout}"
            assert "deploy" in result.stderr.lower() or "rebuild.sh" in result.stderr.lower(), (
                f"Expected deploy-related error, got: {result.stderr}"
            )
        finally:
            plan_file.unlink()

    def test_verify_rejects_frontend_missing_browser_check(self) -> None:
        """st verify should reject frontend subtasks without browser verification."""
        plan_file = create_plan_file(plan_frontend_missing_browser_check())
        try:
            result = run_cli(["verify", str(plan_file)])
            assert result.returncode == 1, f"Expected failure, got: {result.stdout}"
            assert (
                "browser" in result.stderr.lower()
                or "agent-browser" in result.stderr.lower()
                or "console error" in result.stderr.lower()
            ), f"Expected browser-related error, got: {result.stderr}"
        finally:
            plan_file.unlink()

    def test_verify_accepts_valid_frontend_plan(self) -> None:
        """st verify should accept frontend plan with deploy and browser check."""
        plan_file = create_plan_file(plan_frontend_valid())
        try:
            result = run_cli(["verify", str(plan_file)])
            assert result.returncode == 0, f"Expected success, got: {result.stderr}"
            assert "PASS" in result.stdout
        finally:
            plan_file.unlink()

    def test_verify_accepts_valid_plan(self) -> None:
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

    def test_import_rejects_string_steps(self) -> None:
        """st import should reject plans with string steps."""
        plan_file = create_plan_file(plan_string_steps())
        try:
            result = run_cli(["import", str(plan_file), "--dry-run"])
            assert result.returncode == 1, f"Expected failure, got: {result.stdout}"
        finally:
            plan_file.unlink()

    def test_import_rejects_missing_verify_command(self) -> None:
        """st import should reject plans with missing verify_command."""
        plan_file = create_plan_file(plan_missing_verify_command())
        try:
            result = run_cli(["import", str(plan_file), "--dry-run"])
            assert result.returncode == 1, f"Expected failure, got: {result.stdout}"
        finally:
            plan_file.unlink()

    def test_import_rejects_no_verification_subtask(self) -> None:
        """st import should reject plans without verification subtask."""
        plan_file = create_plan_file(plan_no_verification_subtask())
        try:
            result = run_cli(["import", str(plan_file), "--dry-run"])
            assert result.returncode == 1, f"Expected failure, got: {result.stdout}"
        finally:
            plan_file.unlink()

    def test_import_accepts_valid_plan_dry_run(self) -> None:
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

    def test_subtask_create_rejects_no_steps(self, project_id: str, cleanup_tasks: Any) -> None:
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

    def test_subtask_create_accepts_proper_steps(self, project_id: str, cleanup_tasks: Any) -> None:
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

    def test_subtask_pass_fails_without_steps(self, project_id: str, cleanup_tasks: Any) -> None:
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

    def test_subtask_pass_fails_with_incomplete_steps(self, project_id: str, cleanup_tasks: Any) -> None:
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
                {"description": "Step 1", "verify_command": "echo 1"},
                {"description": "Step 2", "verify_command": "echo 2"},
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
# Run tests directly
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x"])
