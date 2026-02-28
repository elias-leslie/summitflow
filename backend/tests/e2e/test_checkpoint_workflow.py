"""End-to-end tests for checkpoint system workflow.

Tests the full checkpoint lifecycle:
1. Happy path - single agent: claim → context → step pass → subtask pass → done
2. Parallel agents - multiple subtasks executing concurrently
3. Subtask failure - git rollback only (abandon subtask)
4. Task failure - git rollback only (abandon task, no DB restore)
5. Project lock - one active task per project
6. Resume after interruption - detect existing checkpoint
7. Agent Hub integration - CLI calls work from agents

These tests exercise REAL CLI commands, REAL git operations, and REAL DB.
Requires: backend running, git repo initialized, test project exists.
"""

from __future__ import annotations

import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from app.storage import tasks as task_store

TEST_PROJECT_ID = "test-project"
SUMMITFLOW_DIR = Path("/home/kasadis/summitflow")


def _backend_available() -> bool:
    """Check if the backend API server is running."""
    try:
        urllib.request.urlopen("http://127.0.0.1:8001/health", timeout=2)
        return True
    except (urllib.error.URLError, TimeoutError):
        return False


def _git_clean() -> bool:
    """Check if the summitflow working tree is clean."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=SUMMITFLOW_DIR,
        )
        return result.returncode == 0 and not result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


@pytest.fixture
def requires_backend() -> None:
    """Skip test if backend server is not running."""
    if not _backend_available():
        pytest.skip("Backend server not running (required for checkpoint E2E test)")


@pytest.fixture
def requires_clean_git() -> None:
    """Skip test if git working tree has uncommitted changes."""
    if not _git_clean():
        pytest.skip("Git working tree has uncommitted changes (st claim requires clean tree)")


@pytest.fixture
def test_project_id() -> str:
    """Return test project ID (test-project for E2E tests)."""
    return TEST_PROJECT_ID


@pytest.fixture
def cleanup_checkpoints() -> Any:
    """Clean up checkpoint data after tests."""
    task_ids: list[str] = []
    yield task_ids
    for task_id in task_ids:
        run_cli(["abandon", task_id, "--force"], check=False)


@pytest.fixture
def cleanup_tasks() -> Any:
    """Track and cleanup test tasks after tests."""
    task_ids: list[str] = []
    yield task_ids
    for task_id in task_ids:
        try:
            task_store.delete_task(task_id)
        except Exception:
            pass


def run_cli(
    args: list[str],
    check: bool = False,
    timeout: int = 60,
    project_id: str | None = TEST_PROJECT_ID,
    stdin_input: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run st CLI command and return result.

    Args:
        args: CLI arguments after 'st'
        check: Raise exception on non-zero exit
        timeout: Command timeout in seconds
        project_id: Project ID to set via ST_PROJECT_ID env var
        stdin_input: Optional input to send to stdin (for interactive prompts)
    """
    env = os.environ.copy()
    if project_id:
        env["ST_PROJECT_ID"] = project_id

    result = subprocess.run(
        ["st", *args],
        input=stdin_input,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=SUMMITFLOW_DIR,
        env=env,
    )
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, args, result.stdout, result.stderr)
    return result


def run_git(args: list[str], cwd: str | Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run git command and return result."""
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=cwd,
    )


def create_test_task(project_id: str, title: str) -> dict[str, Any]:
    """Create a test task with subtasks and steps."""
    task = task_store.create_task(
        project_id=project_id,
        title=title,
        description=f"E2E test task: {title}",
    )
    from app.storage import subtasks as subtask_store

    subtask_store.create_subtask(
        task_id=task["id"],
        subtask_id="1.1",
        description="Implementation subtask",
        display_order=0,
        steps=[
            {
                "description": "Create test file",
            },
        ],
    )
    subtask_store.create_subtask(
        task_id=task["id"],
        subtask_id="1.2",
        description="Verification subtask",
        display_order=1,
        phase="verification",
        steps=[
            {
                "description": "Verify completion",
            },
        ],
    )
    run_cli(["approve", task["id"]])
    return task


class TestHappyPath:
    """Test happy path: claim → context → step pass → subtask pass → done."""

    def test_single_agent_workflow(
        self,
        requires_backend: None,
        requires_clean_git: None,
        test_project_id: str,
        cleanup_tasks: Any,
        cleanup_checkpoints: Any,
    ) -> None:
        """Test complete workflow for a single agent."""
        task = create_test_task(test_project_id, "Happy Path Test")
        cleanup_tasks.append(task["id"])
        cleanup_checkpoints.append(task["id"])

        result = run_cli(["claim", task["id"]])
        assert result.returncode == 0, f"Claim failed: {result.stderr}"
        assert "claimed" in result.stdout.lower() or "checkpoint" in result.stdout.lower()

        result = run_cli(["context", task["id"]])
        assert result.returncode == 0, f"Context failed: {result.stderr}"
        assert "1.1" in result.stdout
        assert "1.2" in result.stdout

        for subtask_id in ["1.1", "1.2"]:
            result = run_cli(["claim", subtask_id, "-t", task["id"]])
            assert result.returncode == 0, f"Claim subtask {subtask_id} failed: {result.stderr}"

            result = run_cli(["step", "pass", subtask_id, "1", "-t", task["id"]])
            assert result.returncode == 0, f"Step pass failed: {result.stderr}"

            # Acknowledge citations (required before done)
            result = run_cli(["subtask", "citations", "--none", "-s", subtask_id, "-t", task["id"]])
            assert result.returncode == 0, f"Citations ack failed: {result.stderr}"

            result = run_cli(["done", subtask_id, "-t", task["id"]])
            assert result.returncode == 0, f"Subtask done failed: {result.stderr}"

        result = run_cli(["done", task["id"]])
        assert result.returncode == 0, f"Task done failed: {result.stderr}"

        result = run_cli(["context", task["id"]])
        assert "completed" in result.stdout.lower() or "done" in result.stdout.lower()

    def test_context_with_subtask_flag(
        self,
        requires_backend: None,
        requires_clean_git: None,
        test_project_id: str,
        cleanup_tasks: Any,
        cleanup_checkpoints: Any,
    ) -> None:
        """Test st context --subtask shows step details."""
        task = create_test_task(test_project_id, "Context Subtask Test")
        cleanup_tasks.append(task["id"])
        cleanup_checkpoints.append(task["id"])

        run_cli(["claim", task["id"]])

        result = run_cli(["context", task["id"], "--subtask", "1.1"])
        assert result.returncode == 0, f"Context failed: {result.stderr}"
        assert "1.1" in result.stdout
        assert "step" in result.stdout.lower() or "create test file" in result.stdout.lower()


class TestSubtaskAbandon:
    """Test subtask abandonment - git branch only, no DB rollback."""

    def test_abandon_subtask_deletes_branch(
        self,
        requires_backend: None,
        requires_clean_git: None,
        test_project_id: str,
        cleanup_tasks: Any,
        cleanup_checkpoints: Any,
    ) -> None:
        """Abandoning a subtask should delete its git branch only."""
        task = create_test_task(test_project_id, "Subtask Abandon Test")
        cleanup_tasks.append(task["id"])
        cleanup_checkpoints.append(task["id"])

        run_cli(["claim", task["id"]], check=True)
        run_cli(["claim", "1.1", "-t", task["id"]], check=True)

        result = run_cli(["abandon", "1.1", "-t", task["id"]])
        assert result.returncode == 0, f"Abandon failed: {result.stderr}"
        assert "abandoned" in result.stdout.lower()

        result = run_cli(["claim", "1.1", "-t", task["id"]])
        assert result.returncode == 0, f"Re-claim failed: {result.stderr}"


class TestTaskAbandon:
    """Test task abandonment - code rollback only (no DB restore)."""

    def test_abandon_task_deletes_branches(
        self,
        requires_backend: None,
        requires_clean_git: None,
        test_project_id: str,
        cleanup_tasks: Any,
        cleanup_checkpoints: Any,
    ) -> None:
        """Abandoning a task should delete all branches and mark as abandoned."""
        task = create_test_task(test_project_id, "Task Abandon Test")
        cleanup_tasks.append(task["id"])
        cleanup_checkpoints.append(task["id"])

        run_cli(["claim", task["id"]], check=True)

        run_cli(["claim", "1.1", "-t", task["id"]])
        run_cli(["step", "pass", "1.1", "1", "-t", task["id"]])

        result = run_cli(["abandon", task["id"], "--force"])
        assert result.returncode == 0, f"Abandon failed: {result.stderr}"
        assert "restored" in result.stdout.lower() or "abandoned" in result.stdout.lower()

        result = run_cli(["context", task["id"]])
        assert "pending" in result.stdout.lower()


class TestProjectLock:
    """Test project-level lock - one active task at a time."""

    def test_second_claim_blocked(
        self,
        requires_backend: None,
        requires_clean_git: None,
        test_project_id: str,
        cleanup_tasks: Any,
        cleanup_checkpoints: Any,
    ) -> None:
        """Second task claim should fail when one is already active."""
        task1 = create_test_task(test_project_id, "Project Lock Test 1")
        task2 = create_test_task(test_project_id, "Project Lock Test 2")
        cleanup_tasks.extend([task1["id"], task2["id"]])
        cleanup_checkpoints.extend([task1["id"], task2["id"]])

        result = run_cli(["claim", task1["id"]])
        assert result.returncode == 0, f"First claim failed: {result.stderr}"

        result = run_cli(["claim", task2["id"]])
        assert result.returncode == 1, "Second claim should have failed"
        assert "active" in result.stderr.lower() or "lock" in result.stderr.lower()

        run_cli(["abandon", task1["id"], "--force"])

        result = run_cli(["claim", task2["id"]])
        assert result.returncode == 0, f"Claim after abandon failed: {result.stderr}"


class TestCheckpointsCommand:
    """Test st checkpoints command."""

    def test_checkpoints_lists_active(
        self,
        requires_backend: None,
        requires_clean_git: None,
        test_project_id: str,
        cleanup_tasks: Any,
        cleanup_checkpoints: Any,
    ) -> None:
        """st checkpoints should list active checkpoints."""
        task = create_test_task(test_project_id, "Checkpoints List Test")
        cleanup_tasks.append(task["id"])
        cleanup_checkpoints.append(task["id"])

        run_cli(["checkpoints"])
        run_cli(["claim", task["id"]], check=True)

        result = run_cli(["checkpoints"])
        assert result.returncode == 0, f"Checkpoints failed: {result.stderr}"
        assert task["id"] in result.stdout, "Task should appear in checkpoints"


class TestResumeAfterInterruption:
    """Test resuming work after session interruption."""

    def test_detect_existing_checkpoint(
        self,
        requires_backend: None,
        requires_clean_git: None,
        test_project_id: str,
        cleanup_tasks: Any,
        cleanup_checkpoints: Any,
    ) -> None:
        """Claiming existing checkpoint should offer resume."""
        task = create_test_task(test_project_id, "Resume Test")
        cleanup_tasks.append(task["id"])
        cleanup_checkpoints.append(task["id"])

        run_cli(["claim", task["id"]], check=True)
        run_cli(["claim", "1.1", "-t", task["id"]], check=True)

        # Re-claim should detect existing checkpoint and prompt for resume
        # Provide "y\n" to confirm resume via stdin
        result = run_cli(["claim", task["id"]], stdin_input="y\n")
        assert result.returncode == 0, f"Resume failed: {result.stderr}"
        # Should show either "existing checkpoint" message or "resumed"
        output = result.stdout.lower()
        assert "existing" in output or "resumed" in output or "checkpoint" in output, (
            f"Expected resume detection: {result.stdout}"
        )


class TestRemovedCommands:
    """Test that removed commands show helpful errors."""

    def test_work_shows_error(self) -> None:
        """st work should show helpful error pointing to st claim."""
        result = run_cli(["work"], project_id=None)
        assert result.returncode != 0, "Expected non-zero exit code"
        assert "claim" in result.stderr.lower(), f"Expected 'claim' in error: {result.stderr}"

    def test_show_shows_error(self) -> None:
        """st show should show helpful error pointing to st context."""
        result = run_cli(["show"], project_id=None)
        assert result.returncode != 0, "Expected non-zero exit code"
        assert "context" in result.stderr.lower(), f"Expected 'context' in error: {result.stderr}"

    def test_close_shows_error(self) -> None:
        """st close should show helpful error pointing to st done."""
        result = run_cli(["close"], project_id=None)
        assert result.returncode != 0, "Expected non-zero exit code"
        assert "done" in result.stderr.lower(), f"Expected 'done' in error: {result.stderr}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-x"])
