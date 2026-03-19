"""End-to-end tests for autonomous execution engine.

Tests the FULL flows with real database state and mocked Agent Hub:
1. Triage: Idea → assess clarity → route (CLEAR → queue, NEEDS_CLARIFICATION → blocked)
2. Planning: Queue → create subtasks → route by complexity
3. Execution: Running → execute subtasks → complete
4. Review: PR Created → AI review → auto-merge (SIMPLE) or human review
5. Escalation: Failures → supervisor guidance → human escalation
6. Ideation: Raw idea → agent expansion → task_spirit + enriched description
7. Partial merge: Mixed results → follow-up task → QA review for passing work
8. Auto-rollback: Merge + failed validation → revert → regression task

Each test creates real database records, mocks Agent Hub, and verifies state transitions.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

from app.services.complexity_assessor import ComplexityTier
from app.storage import tasks as task_store
from app.storage.connection import get_connection
from app.storage.events import get_events_by_trace
from app.storage.subtasks import create_subtask, get_subtasks_for_task
from app.storage.task_spirit import create_task_spirit, get_task_spirit
from app.tasks.autonomous.cleanup import merge_and_cleanup_task_worktree
from app.tasks.autonomous.escalation import check_escalation_needed
from app.tasks.autonomous.exec_modules.completion_handler import handle_partial_completion
from app.tasks.autonomous.execution import start_execution
from app.tasks.autonomous.ideation import ideate_task
from app.tasks.autonomous.planning import create_plan
from app.tasks.autonomous.review import ai_review
from app.tasks.autonomous.triage import triage_idea


@pytest.fixture
def test_project_id() -> str:
    """Ensure test project exists in database."""
    import os
    import subprocess

    project_id = "e2e-test-project"
    root_path = "/tmp/e2e-test"

    # Create the root_path directory if it doesn't exist
    os.makedirs(root_path, exist_ok=True)

    # Initialize git repo if not already initialized
    git_dir = os.path.join(root_path, ".git")
    if not os.path.exists(git_dir):
        subprocess.run(["git", "init"], cwd=root_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"], cwd=root_path, capture_output=True
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=root_path, capture_output=True)
        # Create an initial commit so we have a branch
        subprocess.run(["touch", ".gitkeep"], cwd=root_path, capture_output=True)
        subprocess.run(["git", "add", "."], cwd=root_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"], cwd=root_path, capture_output=True
        )

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO projects (id, name, base_url, root_path)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET root_path = EXCLUDED.root_path""",
            (project_id, "E2E Test Project", "http://localhost:3001", root_path),
        )
        conn.commit()
    return project_id


@pytest.fixture
def cleanup_tasks() -> Generator[list[str]]:
    """Track and cleanup test tasks after tests."""
    task_ids: list[str] = []
    yield task_ids
    if task_ids:
        with get_connection() as conn, conn.cursor() as cur:
            for task_id in task_ids:
                cur.execute(
                    "DELETE FROM subtask_summaries WHERE subtask_id IN (SELECT id FROM task_subtasks WHERE task_id = %s)",
                    (task_id,),
                )
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


def create_mock_agent_response(content: str, session_id: str = "test-session") -> MagicMock:
    """Create a mock Agent Hub response.

    Includes all fields used by execution code: content, session_id, cited_uuids,
    progress_log, context_usage.
    """
    mock_response = MagicMock()
    mock_response.content = content
    mock_response.session_id = session_id
    mock_response.cited_uuids = []
    mock_response.progress_log = None
    mock_response.context_usage = None
    return mock_response


def task_events_contain(task_id: str, substring: str) -> bool:
    """Check if any event for a task contains the given substring.

    Note: progress_log was moved to events table in migration 099.
    Events use trace_id to store task_id.
    """
    events = get_events_by_trace(task_id, limit=100)
    return any(substring in (event.get("message") or "") for event in events)


@pytest.mark.e2e
class TestTriageE2E:
    """End-to-end tests for idea triage flow."""

    def test_clear_idea_moves_to_queue(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """A clear idea should move from pending → queue with complexity set."""
        task = task_store.create_task(
            project_id=test_project_id,
            title="Add logout button to navbar",
            description="Add a logout button to the top-right of the navbar that logs out the user",
            task_type="task",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)
        # Task starts in pending status by default

        mock_response = create_mock_agent_response(
            json.dumps(
                {
                    "status": "CLEAR",
                    "objective": "Add logout button to navbar",
                    "requirements": ["Button in navbar", "Logout API call", "Redirect to login"],
                    "suggested_complexity": "SIMPLE",
                    "clarifying_questions": [],
                    "reasoning": "Clear, well-defined UI task with specific requirements",
                }
            )
        )

        with patch("app.tasks.autonomous.triage.get_sync_client") as mock_client:
            mock_client.return_value.complete.return_value = mock_response
            result = triage_idea(task_id, test_project_id)

        assert result["status"] == "completed"
        assert result["result"]["status"] == "CLEAR"

        updated_task = task_store.get_task(task_id)
        assert updated_task is not None
        assert updated_task["status"] == "queue"
        assert updated_task["complexity"] == "SIMPLE"
        assert task_events_contain(task_id, "Triage complete: CLEAR")

    def test_unclear_idea_moves_to_blocked(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """An unclear idea should move to blocked with clarifying questions."""
        task = task_store.create_task(
            project_id=test_project_id,
            title="Make it faster",
            description="",
            task_type="task",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)

        mock_response = create_mock_agent_response(
            json.dumps(
                {
                    "status": "NEEDS_CLARIFICATION",
                    "clarifying_questions": [
                        "What specifically needs to be faster?",
                        "What is the current performance?",
                        "What is the target performance?",
                    ],
                    "reasoning": "Vague request needs more context",
                }
            )
        )

        with patch("app.tasks.autonomous.triage.get_sync_client") as mock_client:
            mock_client.return_value.complete.return_value = mock_response
            result = triage_idea(task_id, test_project_id)

        assert result["status"] == "completed"
        assert result["result"]["status"] == "NEEDS_CLARIFICATION"

        updated_task = task_store.get_task(task_id)
        assert updated_task is not None
        assert updated_task["status"] == "blocked"
        assert task_events_contain(task_id, "What specifically needs to be faster?")

    def test_missing_task_returns_error(self, test_project_id: str) -> None:
        """Triage on missing task should return error (not raise)."""
        result = triage_idea("nonexistent-task-xyz", test_project_id)
        assert result["status"] == "error"
        assert "not found" in result["message"].lower()


@pytest.mark.e2e
class TestPlanningE2E:
    """End-to-end tests for autonomous planning flow."""

    def test_planning_creates_subtasks_and_routes_simple(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """Planning should create subtasks and route SIMPLE to queue."""
        task = task_store.create_task(
            project_id=test_project_id,
            title="Add loading spinner to button",
            description="Show loading spinner while form submits",
            task_type="task",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)
        task_store.update_task_status(task_id, "queue")

        plan_json = json.dumps(
            {
                "objective": "Add loading state to submit button",
                "subtasks": [
                    {
                        "subtask_id": "1.1",
                        "phase": "frontend",
                        "description": "Add loading prop to Button component",
                        "steps": [
                            {
                                "description": "Add isLoading prop",
                            }
                        ],
                    },
                    {
                        "subtask_id": "1.2",
                        "phase": "frontend",
                        "description": "Connect loading state to form submission",
                        "steps": [
                            {
                                "description": "Update form to track loading",
                            }
                        ],
                    },
                ],
                "constraints": ["Use existing spinner component"],
            }
        )

        mock_response = create_mock_agent_response(plan_json)

        with (
            patch("app.tasks.autonomous.planning.get_sync_client") as mock_client,
            patch("app.tasks.autonomous.planning.ComplexityAssessor") as mock_assessor,
        ):
            mock_client.return_value.complete.return_value = mock_response
            mock_assessor_instance = MagicMock()
            mock_assessor_instance.assess_sync.return_value = MagicMock(
                tier=ComplexityTier.SIMPLE,
                reasoning="Simple UI change",
            )
            mock_assessor.return_value = mock_assessor_instance

            result = create_plan(task_id, test_project_id)

        assert result["status"] == "completed"
        assert result["subtasks_created"] == 2

        subtasks = get_subtasks_for_task(task_id, include_steps=True)
        assert len(subtasks) == 2
        assert subtasks[0]["subtask_id"] == "1.1"
        assert subtasks[0]["phase"] == "frontend"

        spirit = get_task_spirit(task_id)
        assert spirit is not None
        assert spirit["objective"] == "Add loading state to submit button"

        updated_task = task_store.get_task(task_id)
        assert updated_task is not None
        assert updated_task["status"] == "queue"
        assert updated_task["complexity"] == "SIMPLE"

    def test_complex_task_supervisor_approved_queues(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """Complex tasks approved by supervisor should be queued for execution."""
        task = task_store.create_task(
            project_id=test_project_id,
            title="Implement real-time collaboration",
            description="Add real-time editing with conflict resolution using CRDTs",
            task_type="feature",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)
        task_store.update_task_status(task_id, "queue")

        plan_json = json.dumps(
            {
                "objective": "Implement CRDT-based real-time collaboration",
                "subtasks": [
                    {
                        "subtask_id": "1.1",
                        "phase": "research",
                        "description": "Research CRDT libraries",
                        "steps": [{"description": "Compare Yjs vs Automerge"}],
                    },
                    {
                        "subtask_id": "2.1",
                        "phase": "backend",
                        "description": "Set up WebSocket server",
                        "steps": [{"description": "Configure WebSocket with Redis pub/sub"}],
                    },
                ],
                "constraints": ["Must handle offline mode", "Preserve undo history"],
            }
        )

        mock_response = create_mock_agent_response(plan_json)
        mock_supervisor_response = create_mock_agent_response("APPROVED - proceed with execution")

        with (
            patch("app.tasks.autonomous.planning.get_sync_client") as mock_client,
            patch("app.tasks.autonomous.planning.ComplexityAssessor") as mock_assessor,
        ):
            mock_client.return_value.complete.side_effect = [mock_response, mock_supervisor_response]
            mock_assessor_instance = MagicMock()
            mock_assessor_instance.assess_sync.return_value = MagicMock(
                tier=ComplexityTier.COMPLEX,
                reasoning="CRDT implementation requires architecture decisions",
            )
            mock_assessor.return_value = mock_assessor_instance

            result = create_plan(task_id, test_project_id)

        assert result["status"] == "completed"

        updated_task = task_store.get_task(task_id)
        assert updated_task is not None
        assert updated_task["status"] == "queue"
        assert updated_task["complexity"] == "COMPLEX"
        assert task_events_contain(task_id, "Supervisor approved")


@pytest.mark.e2e
class TestExecutionE2E:
    """End-to-end tests for subtask execution flow."""

    def test_execution_completes_all_subtasks(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """Execution should run all subtasks and mark them passed."""
        task = task_store.create_task(
            project_id=test_project_id,
            title="Add test file",
            description="Create a simple test file",
            task_type="task",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)

        create_task_spirit(
            task_id=task_id,
            objective="Create test file",
            constraints=[],
        )

        create_subtask(
            task_id=task_id,
            subtask_id="1.1",
            description="Create test file",
            display_order=0,
            phase="backend",
            steps=[
                {
                    "description": "Create test.py",
                }
            ],
        )

        task_store.update_task_status(task_id, "queue")

        mock_response = create_mock_agent_response("Created test.py successfully")

        with (
            patch(
                "app.tasks.autonomous.exec_modules.agent_execution.get_sync_client"
            ) as mock_client,
            patch(
                "app.tasks.autonomous.exec_modules.orchestrator.setup_worktree",
                return_value="/tmp/e2e-test",
            ),
            patch(
                "app.tasks.autonomous.exec_modules.orchestrator.validate_pristine_codebase",
                return_value=True,
            ),
            patch(
                "app.tasks.autonomous.exec_modules.orchestrator.check_main_repo_leakage",
            ),
            patch(
                "app.tasks.autonomous.exec_modules.completion_handler.handle_successful_completion",
            ),
        ):
            mock_client.return_value.complete.return_value = mock_response
            result = start_execution(task_id, test_project_id)

        assert result["status"] == "executed"
        assert len(result["subtask_results"]) == 1
        assert result["subtask_results"][0]["status"] == "passed"

        subtasks = get_subtasks_for_task(task_id, include_steps=True)
        assert subtasks[0]["passes"]

    def test_execution_handles_verification_failure(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """Execution should process subtasks and handle failures.

        In v2, all subtasks are attempted (with retry loops) and the completion
        handler determines the final outcome. Both subtasks fail here.
        """
        task = task_store.create_task(
            project_id=test_project_id,
            title="Create and verify file",
            description="Create a file and verify it exists",
            task_type="task",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)

        create_task_spirit(task_id=task_id)

        create_subtask(
            task_id=task_id,
            subtask_id="1.1",
            description="Create file that will fail",
            display_order=0,
            phase="backend",
            steps=[
                {
                    "description": "Create nonexistent.py",
                }
            ],
        )

        create_subtask(
            task_id=task_id,
            subtask_id="1.2",
            description="Second subtask with no verification",
            display_order=1,
            phase="backend",
            steps=[{"description": "Should also fail"}],
        )

        task_store.update_task_status(task_id, "queue")

        mock_response = create_mock_agent_response("Created file")

        with (
            patch(
                "app.tasks.autonomous.exec_modules.agent_execution.get_sync_client"
            ) as mock_client,
            patch(
                "app.tasks.autonomous.exec_modules.orchestrator.setup_worktree",
                return_value="/tmp/e2e-test",
            ),
            patch(
                "app.tasks.autonomous.exec_modules.orchestrator.validate_pristine_codebase",
                return_value=True,
            ),
            patch(
                "app.tasks.autonomous.exec_modules.orchestrator.check_main_repo_leakage",
            ),
            patch(
                "app.tasks.autonomous.escalation.get_supervisor_guidance_sync",
                return_value=None,
            ),
            patch(
                "app.tasks.autonomous.exec_modules.memory_writes.get_sync_client",
            ),
        ):
            mock_client.return_value.complete.return_value = mock_response
            result = start_execution(task_id, test_project_id)

        assert result["status"] == "executed"
        # V2: both subtasks are attempted (with retry loops)
        assert len(result["subtask_results"]) == 2
        assert result["subtask_results"][0]["status"] == "failed"
        assert result["subtask_results"][1]["status"] == "failed"

        subtasks = get_subtasks_for_task(task_id, include_steps=True)
        assert subtasks[0]["passes"] is not True
        assert subtasks[1]["passes"] is not True


@pytest.mark.e2e
class TestAIReviewE2E:
    """End-to-end tests for AI review and auto-merge flow."""

    def test_simple_approved_auto_merges(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """SIMPLE task approved by AI should auto-merge and complete."""
        task = task_store.create_task(
            project_id=test_project_id,
            title="Fix typo in README",
            description="Correct spelling error",
            task_type="bug",
            complexity="SIMPLE",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)
        # Transition: pending → running → ai_reviewing
        task_store.update_task_status(task_id, "running")
        task_store.update_task_status(task_id, "ai_reviewing")

        review_json = json.dumps(
            {
                "verdict": "APPROVED",
                "summary": "Simple typo fix, looks good",
                "concerns": [],
                "recommendation": "Merge it",
            }
        )

        mock_response = create_mock_agent_response(review_json)

        with (
            patch("app.tasks.autonomous.review.get_sync_client") as mock_client,
            patch("app.tasks.autonomous.review.get_git_diff") as mock_diff,
            patch("app.tasks.autonomous.review_modules.routing.auto_merge") as mock_merge,
        ):
            mock_client.return_value.complete.return_value = mock_response
            mock_diff.return_value = "- tyop\n+ typo"

            result = ai_review(task_id, test_project_id)

        assert result["status"] == "reviewed"
        assert result["verdict"] == "APPROVED"
        mock_merge.assert_called_once_with(task_id)

        updated_task = task_store.get_task(task_id)
        assert updated_task is not None
        assert updated_task["status"] == "completed"
        assert task_events_contain(task_id, "Auto-merged (SIMPLE)")

    def test_standard_approved_auto_merges(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """STANDARD task approved by AI should auto-merge (no human gate)."""
        task = task_store.create_task(
            project_id=test_project_id,
            title="Add new API endpoint",
            description="Create GET /api/users endpoint",
            task_type="feature",
            complexity="STANDARD",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)
        # Transition: pending → running → ai_reviewing
        task_store.update_task_status(task_id, "running")
        task_store.update_task_status(task_id, "ai_reviewing")

        review_json = json.dumps(
            {
                "verdict": "APPROVED",
                "summary": "New endpoint follows patterns, tests included",
                "concerns": [],
                "recommendation": "Good to merge",
            }
        )

        mock_response = create_mock_agent_response(review_json)

        with (
            patch("app.tasks.autonomous.review.get_sync_client") as mock_client,
            patch("app.tasks.autonomous.review.get_git_diff") as mock_diff,
            patch("app.tasks.autonomous.review_modules.routing.auto_merge") as mock_merge,
        ):
            mock_client.return_value.complete.return_value = mock_response
            mock_diff.return_value = "+ def get_users():"

            result = ai_review(task_id, test_project_id)

        assert result["status"] == "reviewed"
        assert result["verdict"] == "APPROVED"

        updated_task = task_store.get_task(task_id)
        assert updated_task is not None
        assert updated_task["status"] == "completed"
        mock_merge.assert_called_once_with(task_id)

    def test_rejected_creates_fix_subtask(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """Rejected review should create fix subtask and re-queue."""
        task = task_store.create_task(
            project_id=test_project_id,
            title="Add validation",
            description="Add input validation to form",
            task_type="task",
            complexity="SIMPLE",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)
        # Transition: pending → running → ai_reviewing
        task_store.update_task_status(task_id, "running")
        task_store.update_task_status(task_id, "ai_reviewing")

        review_json = json.dumps(
            {
                "verdict": "REJECT",
                "summary": "Validation is incomplete",
                "concerns": ["Missing email format check", "No error messages"],
                "recommendation": "Add email regex and user-friendly error messages",
            }
        )

        mock_response = create_mock_agent_response(review_json)

        with (
            patch("app.tasks.autonomous.review.get_sync_client") as mock_client,
            patch("app.tasks.autonomous.review.get_git_diff") as mock_diff,
        ):
            mock_client.return_value.complete.return_value = mock_response
            mock_diff.return_value = "+ if not email:"

            result = ai_review(task_id, test_project_id)

        assert result["status"] == "reviewed"
        assert result["verdict"] == "REJECT"

        updated_task = task_store.get_task(task_id)
        assert updated_task is not None
        # REJECT verdict transitions to running (ready for re-execution)
        assert updated_task["status"] == "running"
        assert task_events_contain(task_id, "REJECT")

        subtasks = get_subtasks_for_task(task_id, include_steps=True)
        fix_subtasks = [s for s in subtasks if s["subtask_id"] == "99.1"]
        assert len(fix_subtasks) == 1
        assert "email" in fix_subtasks[0]["description"].lower()


@pytest.mark.e2e
class TestEscalationE2E:
    """End-to-end tests for 3-2-1 escalation pattern."""

    def test_no_escalation_below_threshold(self) -> None:
        """First failures should not trigger escalation."""
        result = check_escalation_needed(failure_count=1, supervisor_attempts=0)
        assert not result["escalate_to_supervisor"]
        assert not result["escalate_to_pipeline"]

        result = check_escalation_needed(failure_count=2, supervisor_attempts=0)
        assert not result["escalate_to_supervisor"]
        assert not result["escalate_to_pipeline"]

    def test_escalate_to_supervisor_at_3_failures(self) -> None:
        """3 worker failures should trigger supervisor escalation."""
        result = check_escalation_needed(failure_count=3, supervisor_attempts=0)
        assert result["escalate_to_supervisor"]
        assert not result["escalate_to_pipeline"]

    def test_escalate_to_pipeline_at_2_supervisor_attempts(self) -> None:
        """2 supervisor attempts should trigger pipeline escalation."""
        result = check_escalation_needed(failure_count=3, supervisor_attempts=2)
        # Once pipeline escalation is triggered, supervisor escalation is False
        assert not result["escalate_to_supervisor"]
        assert result["escalate_to_pipeline"]

    def test_escalation_thresholds_match_321_pattern(self) -> None:
        """Verify 3-2-1 pattern: 3 worker, 2 supervisor, 1 human."""
        from app.tasks.autonomous.escalation import (
            SUPERVISOR_MAX_ATTEMPTS,
            WORKER_MAX_FAILURES,
        )

        assert WORKER_MAX_FAILURES == 3
        assert SUPERVISOR_MAX_ATTEMPTS == 2


@pytest.mark.e2e
class TestFullAutonomousPipeline:
    """Integration tests for the complete autonomous pipeline."""

    def test_full_pipeline_simple_task(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """Test complete flow: triage → plan → execute → review → complete."""
        task = task_store.create_task(
            project_id=test_project_id,
            title="Add console.log for debugging",
            description="Add console.log to track API calls",
            task_type="task",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)

        triage_response = create_mock_agent_response(
            json.dumps(
                {
                    "status": "CLEAR",
                    "suggested_complexity": "SIMPLE",
                    "clarifying_questions": [],
                }
            )
        )

        with patch("app.tasks.autonomous.triage.get_sync_client") as mock_client:
            mock_client.return_value.complete.return_value = triage_response
            triage_result = triage_idea(task_id, test_project_id)

        assert triage_result["status"] == "completed"
        task_data = task_store.get_task(task_id)
        assert task_data is not None
        assert task_data["status"] == "queue"

        plan_response = create_mock_agent_response(
            json.dumps(
                {
                    "objective": "Add debug logging",
                    "subtasks": [
                        {
                            "subtask_id": "1.1",
                            "phase": "frontend",
                            "description": "Add console.log to API client",
                            "steps": [
                                {
                                    "description": "Add logging statement",
                                }
                            ],
                        }
                    ],
                    "constraints": [],
                }
            )
        )

        with (
            patch("app.tasks.autonomous.planning.get_sync_client") as mock_client,
            patch("app.tasks.autonomous.planning.ComplexityAssessor") as mock_assessor,
        ):
            # Planning uses client.complete(), not run_agent()
            mock_client.return_value.complete.return_value = plan_response
            mock_assessor_instance = MagicMock()
            mock_assessor_instance.assess_sync.return_value = MagicMock(
                tier=ComplexityTier.SIMPLE,
                reasoning="Simple logging task",
            )
            mock_assessor.return_value = mock_assessor_instance

            plan_result = create_plan(task_id, test_project_id)

        assert plan_result["status"] == "completed"
        assert plan_result["subtasks_created"] == 1

        exec_response = create_mock_agent_response("Added console.log to API client")

        with (
            patch(
                "app.tasks.autonomous.exec_modules.agent_execution.get_sync_client"
            ) as mock_client,
            patch(
                "app.tasks.autonomous.exec_modules.orchestrator.setup_worktree",
                return_value="/tmp/e2e-test",
            ),
            patch(
                "app.tasks.autonomous.exec_modules.orchestrator.validate_pristine_codebase",
                return_value=True,
            ),
            patch(
                "app.tasks.autonomous.exec_modules.orchestrator.check_main_repo_leakage",
            ),
            patch(
                "app.tasks.autonomous.exec_modules.completion_handler.handle_successful_completion",
            ),
        ):
            mock_client.return_value.complete.return_value = exec_response
            exec_result = start_execution(task_id, test_project_id)

        assert exec_result["status"] == "executed"
        assert exec_result["subtask_results"][0]["status"] == "passed"

        review_response = create_mock_agent_response(
            json.dumps(
                {
                    "verdict": "APPROVED",
                    "summary": "Simple logging addition",
                    "concerns": [],
                }
            )
        )

        with (
            patch("app.tasks.autonomous.review.get_sync_client") as mock_client,
            patch("app.tasks.autonomous.review.get_git_diff") as mock_diff,
            patch("app.tasks.autonomous.review_modules.routing.auto_merge") as mock_merge,
        ):
            mock_client.return_value.complete.return_value = review_response
            mock_diff.return_value = "+ console.log('API call')"

            review_result = ai_review(task_id, test_project_id)

        assert review_result["status"] == "reviewed"
        assert review_result["verdict"] == "APPROVED"
        mock_merge.assert_called_once_with(task_id)

        final_task = task_store.get_task(task_id)
        assert final_task is not None
        assert final_task["status"] == "completed"
        assert task_events_contain(task_id, "Auto-merged (SIMPLE)")


@pytest.mark.e2e
class TestIdeationE2E:
    """End-to-end tests for ideation stage (raw idea expansion)."""

    def test_ideation_expands_idea_creates_spirit(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """Ideation should expand a raw idea and create task_spirit with objective."""
        task = task_store.create_task(
            project_id=test_project_id,
            title="Better search",
            description="Make search better somehow",
            task_type="task",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)

        ideation_json = json.dumps(
            {
                "objective": "Implement fuzzy search with typo tolerance using Levenshtein distance",
                "scope": "Backend search API only; frontend changes out of scope",
                "acceptance_criteria": [
                    "Search returns results for misspelled queries",
                    "Response time < 200ms for fuzzy matches",
                ],
                "suggested_type": "feature",
                "complexity": "STANDARD",
                "dependencies": [],
                "enriched_description": (
                    "Add fuzzy matching to the search endpoint using Levenshtein distance. "
                    "The search API should tolerate up to 2 character edits per word."
                ),
            }
        )

        mock_response = create_mock_agent_response(ideation_json)

        with patch("app.tasks.autonomous.ideation.get_sync_client") as mock_client:
            mock_client.return_value.complete.return_value = mock_response
            result = ideate_task(task_id, test_project_id)

        assert result["status"] == "ideated"
        assert "fuzzy search" in result["objective"].lower()
        assert result["complexity"] == "STANDARD"

        # Verify task_spirit created with objective and scope
        spirit = get_task_spirit(task_id)
        assert spirit is not None
        assert "fuzzy search" in spirit["objective"].lower()
        assert "Backend search API" in spirit.get("context", "")

        # Verify task updated with enriched details
        updated_task = task_store.get_task(task_id)
        assert updated_task is not None
        assert updated_task["enrichment_status"] == "accepted"
        assert updated_task["enriched_by"] == "ideator"
        assert updated_task["task_type"] == "feature"
        assert updated_task["complexity"] == "STANDARD"
        assert "Levenshtein" in (updated_task["description"] or "")

        # Verify event logged
        assert task_events_contain(task_id, "Ideation complete")

    def test_ideation_missing_task_returns_error(self, test_project_id: str) -> None:
        """Ideation on missing task should return error."""
        result = ideate_task("nonexistent-ideation-xyz", test_project_id)
        assert result["status"] == "error"
        assert result["reason"] == "task_not_found"

    def test_ideation_no_objective_returns_unclear(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """When ideator response has no extractable objective, return unclear."""
        task = task_store.create_task(
            project_id=test_project_id,
            title="Do something",
            description="",
            task_type="task",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)

        # Return JSON without an objective field
        mock_response = create_mock_agent_response(
            json.dumps({"notes": "Too vague to define", "suggestions": []})
        )

        with patch("app.tasks.autonomous.ideation.get_sync_client") as mock_client:
            mock_client.return_value.complete.return_value = mock_response
            result = ideate_task(task_id, test_project_id)

        assert result["status"] == "unclear"
        assert result["reason"] == "no_objective_produced"

        # No spirit should be created
        spirit = get_task_spirit(task_id)
        assert spirit is None or not spirit.get("objective")

    def test_ideation_agent_error_returns_error(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """Agent Hub failure during ideation should return error status."""
        task = task_store.create_task(
            project_id=test_project_id,
            title="Some idea",
            description="An idea that will fail in ideation",
            task_type="task",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)

        with patch("app.tasks.autonomous.ideation.get_sync_client") as mock_client:
            mock_client.return_value.complete.side_effect = ConnectionError("Agent Hub down")
            result = ideate_task(task_id, test_project_id)

        assert result["status"] == "error"
        assert "Agent Hub down" in result["error"]
        assert task_events_contain(task_id, "Ideation failed")


@pytest.mark.e2e
class TestPartialMergeE2E:
    """End-to-end tests for partial merge completion flow."""

    def test_partial_completion_creates_followup_task(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """Partial completion should create follow-up task and dispatch for review."""
        task = task_store.create_task(
            project_id=test_project_id,
            title="Multi-step feature",
            description="A feature with multiple subtasks",
            task_type="feature",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)
        task_store.update_task_status(task_id, "running")

        # Create two subtasks (one will pass, one will fail)
        create_subtask(
            task_id=task_id,
            subtask_id="1.1",
            description="Add API endpoint",
            display_order=0,
            phase="backend",
            steps=[{"description": "Create endpoint"}],
        )
        create_subtask(
            task_id=task_id,
            subtask_id="1.2",
            description="Add frontend component",
            display_order=1,
            phase="frontend",
            steps=[{"description": "Create component"}],
        )

        # Simulate mixed execution results
        results = [
            {
                "subtask_id": "1.1",
                "status": "passed",
                "self_fix_attempts": 0,
                "supervisor_guided_attempts": 0,
            },
            {
                "subtask_id": "1.2",
                "status": "failed",
                "error": "Component tests failing",
                "self_fix_attempts": 3,
                "supervisor_guided_attempts": 2,
            },
        ]

        dispatch = MagicMock()
        success = handle_partial_completion(
            task_id, test_project_id, "/tmp/e2e-test", results, dispatch
        )

        assert success

        # Verify original task moved to ai_reviewing
        updated_task = task_store.get_task(task_id)
        assert updated_task is not None
        assert updated_task["status"] == "ai_reviewing"

        # Verify verification_result has partial merge info
        vr = updated_task.get("verification_result") or {}
        assert vr.get("partial_merge")
        assert vr.get("passed_count") == 1
        assert vr.get("failed_count") == 1

        # Verify dispatch was called for review
        dispatch.assert_called_once_with("review", task_id, test_project_id)

        # Verify follow-up task was created
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, title, parent_task_id, priority FROM tasks WHERE parent_task_id = %s",
                (task_id,),
            )
            follow_ups = cur.fetchall()

        assert len(follow_ups) == 1
        follow_up_id, follow_up_title, parent_id, priority = follow_ups[0]
        cleanup_tasks.append(follow_up_id)
        assert "stuck subtasks" in follow_up_title.lower() or task_id in follow_up_title
        assert parent_id == task_id
        assert priority == 1  # High priority

    def test_partial_completion_all_passed_returns_false(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """When all results passed, partial completion should return False (nothing to do)."""
        task = task_store.create_task(
            project_id=test_project_id,
            title="All-pass task",
            description="Everything works",
            task_type="task",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)
        task_store.update_task_status(task_id, "running")

        results = [
            {"subtask_id": "1.1", "status": "passed"},
            {"subtask_id": "1.2", "status": "passed"},
        ]

        success = handle_partial_completion(
            task_id, test_project_id, "/tmp/e2e-test", results
        )

        assert not success

    def test_partial_completion_all_failed_returns_false(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """When all results failed, partial completion should return False."""
        task = task_store.create_task(
            project_id=test_project_id,
            title="All-fail task",
            description="Nothing works",
            task_type="task",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)
        task_store.update_task_status(task_id, "running")

        results = [
            {"subtask_id": "1.1", "status": "failed", "error": "timeout"},
            {"subtask_id": "1.2", "status": "failed", "error": "crash"},
        ]

        success = handle_partial_completion(
            task_id, test_project_id, "/tmp/e2e-test", results
        )

        assert not success


@pytest.mark.e2e
class TestAutoRollbackE2E:
    """End-to-end tests for merge + auto-rollback on post-merge validation failure."""

    def test_successful_merge_completes(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """Successful merge with passing validation should return merged status."""
        task = task_store.create_task(
            project_id=test_project_id,
            title="Merge-ready task",
            description="A completed task ready to merge",
            task_type="task",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)
        task_store.update_task_status(task_id, "running")
        task_store.update_task_status(task_id, "completed")

        mock_worktree = MagicMock()
        mock_worktree.branch = f"{task_id}/main"
        mock_worktree.base_branch = "main"
        mock_worktree.path = f"/tmp/worktrees/{task_id}"

        mock_subprocess_success = MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch(
                "app.tasks.autonomous.cleanup.get_task_worktree",
                return_value=mock_worktree,
            ),
            patch(
                "app.tasks.autonomous.cleanup.get_project_root_path",
                return_value="/tmp/e2e-test",
            ),
            patch(
                "app.tasks.autonomous.cleanup.subprocess.run",
                return_value=mock_subprocess_success,
            ),
            patch(
                "app.tasks.autonomous.cleanup.remove_task_worktree",
            ),
            patch(
                "app.tasks.autonomous.cleanup._run_post_merge_validation",
                return_value=True,
            ),
        ):
            result = merge_and_cleanup_task_worktree(task_id, test_project_id)

        assert result["status"] == "merged"
        assert result["task_branch"] == f"{task_id}/main"
        assert result["base_branch"] == "main"
        assert result["post_merge_valid"]

    def test_merge_with_failed_validation_triggers_rollback(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """Failed post-merge validation should trigger auto-rollback."""
        task = task_store.create_task(
            project_id=test_project_id,
            title="Regression-causing task",
            description="This merge will fail validation",
            task_type="task",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)
        task_store.update_task_status(task_id, "running")
        task_store.update_task_status(task_id, "completed")

        mock_worktree = MagicMock()
        mock_worktree.branch = f"{task_id}/main"
        mock_worktree.base_branch = "main"
        mock_worktree.path = f"/tmp/worktrees/{task_id}"

        mock_subprocess_success = MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch(
                "app.tasks.autonomous.cleanup.get_task_worktree",
                return_value=mock_worktree,
            ),
            patch(
                "app.tasks.autonomous.cleanup.get_project_root_path",
                return_value="/tmp/e2e-test",
            ),
            patch(
                "app.tasks.autonomous.cleanup.subprocess.run",
                return_value=mock_subprocess_success,
            ),
            patch(
                "app.tasks.autonomous.cleanup.remove_task_worktree",
            ),
            patch(
                "app.tasks.autonomous.cleanup._run_post_merge_validation",
                return_value=False,
            ),
            patch(
                "app.tasks.autonomous.cleanup._auto_rollback",
                return_value=True,
            ) as mock_rollback,
        ):
            result = merge_and_cleanup_task_worktree(task_id, test_project_id)

        assert result["status"] == "rolled_back"
        assert result["reason"] == "post_merge_validation_failed"
        mock_rollback.assert_called_once_with(
            task_id, "/tmp/e2e-test", test_project_id, f"{task_id}/main"
        )

    def test_auto_rollback_reverts_and_creates_regression_task(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """Full auto-rollback should revert merge, create regression task, block original."""
        from app.tasks.autonomous.cleanup import _auto_rollback

        task = task_store.create_task(
            project_id=test_project_id,
            title="Task causing regression",
            description="This task's merge breaks things",
            task_type="task",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)
        # ai_reviewing → blocked is a valid transition (completed → blocked is not)
        task_store.update_task_status(task_id, "running")
        task_store.update_task_status(task_id, "ai_reviewing")

        mock_revert_success = MagicMock(returncode=0, stdout="", stderr="")
        task_branch = f"{task_id}/main"

        with (
            patch(
                "app.tasks.autonomous.cleanup.subprocess.run",
                return_value=mock_revert_success,
            ),
            patch("app.services.agent_hub_client.get_sync_client"),
        ):
            success = _auto_rollback(task_id, "/tmp/e2e-test", test_project_id, task_branch)

        assert success

        # Verify original task is now blocked
        updated_task = task_store.get_task(task_id)
        assert updated_task is not None
        assert updated_task["status"] == "blocked"

        # Verify rollback event logged
        assert task_events_contain(task_id, "Auto-rollback")
        assert task_events_contain(task_id, "Reverted merge")

        # Verify regression fix task was created
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, title, task_type, parent_task_id, priority FROM tasks WHERE parent_task_id = %s",
                (task_id,),
            )
            regression_tasks = cur.fetchall()

        assert len(regression_tasks) == 1
        reg_id, reg_title, reg_type, reg_parent, reg_priority = regression_tasks[0]
        cleanup_tasks.append(reg_id)
        assert "regression" in reg_title.lower() or task_id in reg_title
        assert reg_type == "regression"
        assert reg_parent == task_id
        assert reg_priority == 1

    def test_merge_blocked_when_task_running(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """Should not merge when task is still running."""
        task = task_store.create_task(
            project_id=test_project_id,
            title="Still running task",
            description="Not ready for merge",
            task_type="task",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)
        task_store.update_task_status(task_id, "running")

        result = merge_and_cleanup_task_worktree(task_id, test_project_id)

        assert result["status"] == "blocked"
        assert result["reason"] == "task_still_running"


@pytest.mark.e2e
class TestIntentOnlyAcceptanceE2E:
    """End-to-end tests for intent-only task acceptance path.

    Intent-only tasks have an objective but empty/missing done_when.
    They should trivially pass the intent check and complete normally.
    """

    def test_intent_only_completes_without_done_when(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """Intent-only task (objective set, done_when=[]) completes through quality gate."""
        task = task_store.create_task(
            project_id=test_project_id,
            title="Build login form",
            description="Build a login form with email and password fields",
            task_type="feature",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)

        create_task_spirit(
            task_id=task_id,
            objective="Build a login form with email and password",
            constraints=[],
            done_when=[],
        )

        create_subtask(
            task_id=task_id,
            subtask_id="1.1",
            description="Create login form component",
            display_order=0,
            phase="frontend",
            steps=[{"description": "Add email and password inputs"}],
        )

        task_store.update_task_status(task_id, "queue")

        mock_response = create_mock_agent_response("Created login form component successfully")

        with (
            patch(
                "app.tasks.autonomous.exec_modules.agent_execution.get_sync_client"
            ) as mock_client,
            patch(
                "app.tasks.autonomous.exec_modules.orchestrator.setup_worktree",
                return_value="/tmp/e2e-test",
            ),
            patch(
                "app.tasks.autonomous.exec_modules.orchestrator.validate_pristine_codebase",
                return_value=True,
            ),
            patch(
                "app.tasks.autonomous.exec_modules.orchestrator.check_main_repo_leakage",
            ),
            patch(
                "app.tasks.autonomous.exec_modules.completion_handler.run_quality_gate_with_autofix",
                return_value=True,
            ),
            patch(
                "app.tasks.autonomous.exec_modules.completion_handler.wake_persona",
            ),
            patch(
                "app.storage.agent_configs.get_require_review",
                return_value=False,
            ),
        ):
            mock_client.return_value.complete.return_value = mock_response
            result = start_execution(task_id, test_project_id)

        assert result["status"] == "executed"
        assert len(result["subtask_results"]) == 1
        assert result["subtask_results"][0]["status"] == "passed"

        updated_task = task_store.get_task(task_id)
        assert updated_task is not None
        assert updated_task["status"] == "completed"

        vr = updated_task.get("verification_result") or {}
        assert vr.get("execution_clean")

        assert not task_events_contain(task_id, "Intent check failed")

    def test_intent_only_no_spirit_skips_check(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """Task with no task_spirit skips intent check and completes normally."""
        task = task_store.create_task(
            project_id=test_project_id,
            title="Fix null pointer in user service",
            description="Resolve NPE when user has no profile",
            task_type="bug",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)

        # No task_spirit created — intent check returns trivial pass ("No spirit data")
        create_subtask(
            task_id=task_id,
            subtask_id="1.1",
            description="Guard against null user profile",
            display_order=0,
            phase="backend",
            steps=[{"description": "Add null check before profile access"}],
        )

        task_store.update_task_status(task_id, "queue")

        mock_response = create_mock_agent_response("Added null check for user profile")

        with (
            patch(
                "app.tasks.autonomous.exec_modules.agent_execution.get_sync_client"
            ) as mock_client,
            patch(
                "app.tasks.autonomous.exec_modules.orchestrator.setup_worktree",
                return_value="/tmp/e2e-test",
            ),
            patch(
                "app.tasks.autonomous.exec_modules.orchestrator.validate_pristine_codebase",
                return_value=True,
            ),
            patch(
                "app.tasks.autonomous.exec_modules.orchestrator.check_main_repo_leakage",
            ),
            patch(
                "app.tasks.autonomous.exec_modules.completion_handler.run_quality_gate_with_autofix",
                return_value=True,
            ),
            patch(
                "app.tasks.autonomous.exec_modules.completion_handler.wake_persona",
            ),
            patch(
                "app.storage.agent_configs.get_require_review",
                return_value=False,
            ),
        ):
            mock_client.return_value.complete.return_value = mock_response
            result = start_execution(task_id, test_project_id)

        assert result["status"] == "executed"
        assert result["subtask_results"][0]["status"] == "passed"

        updated_task = task_store.get_task(task_id)
        assert updated_task is not None
        assert updated_task["status"] == "completed"

        assert not task_events_contain(task_id, "Intent check failed")

    def test_intent_only_routes_to_review_when_enabled(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """Intent-only task routes to ai_reviewing when require_review=True."""
        task = task_store.create_task(
            project_id=test_project_id,
            title="Add dark mode toggle",
            description="Add theme toggle to settings page",
            task_type="feature",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)

        create_task_spirit(
            task_id=task_id,
            objective="Add dark mode toggle to settings",
            constraints=[],
            done_when=[],
        )

        create_subtask(
            task_id=task_id,
            subtask_id="1.1",
            description="Implement theme toggle",
            display_order=0,
            phase="frontend",
            steps=[{"description": "Add toggle switch to settings page"}],
        )

        task_store.update_task_status(task_id, "queue")

        mock_response = create_mock_agent_response("Added dark mode toggle")

        with (
            patch(
                "app.tasks.autonomous.exec_modules.agent_execution.get_sync_client"
            ) as mock_client,
            patch(
                "app.tasks.autonomous.exec_modules.orchestrator.setup_worktree",
                return_value="/tmp/e2e-test",
            ),
            patch(
                "app.tasks.autonomous.exec_modules.orchestrator.validate_pristine_codebase",
                return_value=True,
            ),
            patch(
                "app.tasks.autonomous.exec_modules.orchestrator.check_main_repo_leakage",
            ),
            patch(
                "app.tasks.autonomous.exec_modules.completion_handler.run_quality_gate_with_autofix",
                return_value=True,
            ),
            patch(
                "app.tasks.autonomous.exec_modules.completion_handler.wake_persona",
            ),
            patch(
                "app.storage.agent_configs.get_require_review",
                return_value=True,
            ),
        ):
            mock_client.return_value.complete.return_value = mock_response
            result = start_execution(task_id, test_project_id)

        assert result["status"] == "executed"
        assert result["subtask_results"][0]["status"] == "passed"

        updated_task = task_store.get_task(task_id)
        assert updated_task is not None
        assert updated_task["status"] == "ai_reviewing"

        assert not task_events_contain(task_id, "Intent check failed")

    def test_intent_only_with_done_when_calls_reviewer(
        self, test_project_id: str, cleanup_tasks: list[str]
    ) -> None:
        """Control: task WITH done_when triggers full intent evaluation via reviewer agent."""
        task = task_store.create_task(
            project_id=test_project_id,
            title="Add API health endpoint",
            description="Create GET /api/health returning 200",
            task_type="feature",
        )
        task_id = task["id"]
        cleanup_tasks.append(task_id)

        create_task_spirit(
            task_id=task_id,
            objective="Create health check endpoint",
            constraints=[],
            done_when=["API returns 200 on GET /api/health"],
        )

        create_subtask(
            task_id=task_id,
            subtask_id="1.1",
            description="Implement health check endpoint",
            display_order=0,
            phase="backend",
            steps=[{"description": "Add GET /api/health route"}],
        )

        task_store.update_task_status(task_id, "queue")

        agent_exec_response = create_mock_agent_response("Created health endpoint successfully")

        # Reviewer response with PASS verdict for the done_when criterion
        reviewer_pass_content = (
            "DONE_WHEN_1: PASS - Health endpoint created and returns 200\n"
            "OBJECTIVE_MET: YES\n"
            "SPIRIT_VIOLATED: NO\n"
            "SUMMARY: Health endpoint implementation complete\n"
        )
        reviewer_response = create_mock_agent_response(reviewer_pass_content)

        mock_reviewer_client = MagicMock()
        mock_reviewer_client.complete.return_value = reviewer_response

        with (
            patch(
                "app.tasks.autonomous.exec_modules.agent_execution.get_sync_client"
            ) as mock_exec_client,
            patch(
                "app.tasks.autonomous.exec_modules.orchestrator.setup_worktree",
                return_value="/tmp/e2e-test",
            ),
            patch(
                "app.tasks.autonomous.exec_modules.orchestrator.validate_pristine_codebase",
                return_value=True,
            ),
            patch(
                "app.tasks.autonomous.exec_modules.orchestrator.check_main_repo_leakage",
            ),
            patch(
                "app.tasks.autonomous.exec_modules.completion_handler.run_quality_gate_with_autofix",
                return_value=True,
            ),
            patch(
                "app.tasks.autonomous.exec_modules.completion_handler.wake_persona",
            ),
            patch(
                "app.storage.agent_configs.get_require_review",
                return_value=False,
            ),
            patch(
                "app.services.agent_hub_client.get_sync_client",
                return_value=mock_reviewer_client,
            ),
        ):
            mock_exec_client.return_value.complete.return_value = agent_exec_response
            result = start_execution(task_id, test_project_id)

        assert result["status"] == "executed"
        assert result["subtask_results"][0]["status"] == "passed"

        # Reviewer was called exactly once (done_when triggered full evaluation)
        mock_reviewer_client.complete.assert_called_once()

        updated_task = task_store.get_task(task_id)
        assert updated_task is not None
        assert updated_task["status"] == "completed"

        assert not task_events_contain(task_id, "Intent check failed")
