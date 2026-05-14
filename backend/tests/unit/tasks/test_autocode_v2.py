"""Unit tests for Autocode V2 features.

Tests cover:
- T3: _determine_next_stage routing (pickup.py)
- T5: Agent routing (agent_routing.py)
- T8: Memory write points (memory_writes.py)
- T9: Resume context builder (prompts.py)
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

# =============================================================================
# T3: _determine_next_stage routing
# =============================================================================


class TestDetermineNextStage:
    """Tests for _determine_next_stage in pickup.py."""

    @patch("app.tasks.autonomous.pickup_queries.get_subtasks_for_task")
    @patch("app.tasks.autonomous.pickup_queries.get_task_spirit")
    @patch("app.tasks.autonomous.pickup_queries.task_store")
    def test_crowdsourced_no_spirit_returns_ideation(
        self, mock_store: MagicMock, mock_spirit: MagicMock, mock_subtasks: MagicMock
    ) -> None:
        """Crowdsourced task with no spirit → ideation."""
        from app.tasks.autonomous.pickup import _determine_next_stage

        mock_store.get_task.return_value = {"labels": ["crowdsourced"]}
        mock_spirit.return_value = None
        mock_subtasks.return_value = []

        assert _determine_next_stage("task-1") == "ideation"

    @patch("app.tasks.autonomous.pickup_queries.get_subtasks_for_task")
    @patch("app.tasks.autonomous.pickup_queries.get_task_spirit")
    @patch("app.tasks.autonomous.pickup_queries.task_store")
    def test_crowdsourced_no_objective_returns_ideation(
        self, mock_store: MagicMock, mock_spirit: MagicMock, mock_subtasks: MagicMock
    ) -> None:
        """Crowdsourced task with spirit but no objective → ideation."""
        from app.tasks.autonomous.pickup import _determine_next_stage

        mock_store.get_task.return_value = {"labels": ["crowdsourced"]}
        mock_spirit.return_value = {"objective": None}
        mock_subtasks.return_value = []

        assert _determine_next_stage("task-1") == "ideation"

    @patch("app.tasks.autonomous.pickup_queries.get_subtasks_for_task")
    @patch("app.tasks.autonomous.pickup_queries.get_task_spirit")
    @patch("app.tasks.autonomous.pickup_queries.task_store")
    def test_crowdsourced_with_spirit_no_subtasks_returns_planning(
        self, mock_store: MagicMock, mock_spirit: MagicMock, mock_subtasks: MagicMock
    ) -> None:
        """Crowdsourced task with spirit + description but no subtasks → planning."""
        from app.tasks.autonomous.pickup import _determine_next_stage

        mock_store.get_task.return_value = {"labels": ["crowdsourced"], "description": "Build a widget"}
        mock_spirit.return_value = {"done_when": ["Widget works"]}
        mock_subtasks.return_value = []

        assert _determine_next_stage("task-1") == "planning"

    @patch("app.tasks.autonomous.pickup_queries.get_subtasks_for_task")
    @patch("app.tasks.autonomous.pickup_queries.get_task_spirit")
    @patch("app.tasks.autonomous.pickup_queries.task_store")
    def test_no_crowdsourced_no_spirit_returns_triage(
        self, mock_store: MagicMock, mock_spirit: MagicMock, mock_subtasks: MagicMock
    ) -> None:
        """Non-crowdsourced task with no spirit → triage (not ideation)."""
        from app.tasks.autonomous.pickup import _determine_next_stage

        mock_store.get_task.return_value = {"labels": []}
        mock_spirit.return_value = None
        mock_subtasks.return_value = []

        assert _determine_next_stage("task-1") == "triage"

    @patch("app.tasks.autonomous.pickup_queries.get_subtasks_for_task")
    @patch("app.tasks.autonomous.pickup_queries.get_task_spirit")
    @patch("app.tasks.autonomous.pickup_queries.task_store")
    def test_with_spirit_no_subtasks_returns_planning(
        self, mock_store: MagicMock, mock_spirit: MagicMock, mock_subtasks: MagicMock
    ) -> None:
        """Task with spirit + description but no subtasks → planning."""
        from app.tasks.autonomous.pickup import _determine_next_stage

        mock_store.get_task.return_value = {"labels": [], "description": "Add API endpoint"}
        mock_spirit.return_value = {"done_when": ["Endpoint returns 200"]}
        mock_subtasks.return_value = []

        assert _determine_next_stage("task-1") == "planning"

    @patch("app.tasks.autonomous.pickup_queries.get_subtasks_for_task")
    @patch("app.tasks.autonomous.pickup_queries.get_task_spirit")
    @patch("app.tasks.autonomous.pickup_queries.task_store")
    def test_existing_plan_artifacts_without_subtasks_return_planning(
        self,
        mock_store: MagicMock,
        mock_spirit: MagicMock,
        mock_subtasks: MagicMock,
    ) -> None:
        from app.tasks.autonomous.pickup import _determine_next_stage

        mock_store.get_task.return_value = {
            "labels": [],
            "description": "Add API endpoint",
        }
        mock_spirit.return_value = {
            "done_when": ["Endpoint returns 200"],
            "context": {"planning_signature": "sig-unchanged"},
            "plan_status": "draft",
        }
        mock_subtasks.return_value = []

        assert _determine_next_stage("task-1") == "planning"

    @patch("app.tasks.autonomous.pickup_queries.get_subtasks_for_task")
    @patch("app.tasks.autonomous.pickup_queries.get_task_spirit")
    @patch("app.tasks.autonomous.pickup_queries.task_store")
    def test_with_incomplete_subtasks_returns_execution(
        self, mock_store: MagicMock, mock_spirit: MagicMock, mock_subtasks: MagicMock
    ) -> None:
        """Task with incomplete subtasks → execution."""
        from app.tasks.autonomous.pickup import _determine_next_stage

        mock_store.get_task.return_value = {"labels": [], "description": "Add API endpoint"}
        mock_spirit.return_value = {"done_when": ["Endpoint returns 200"]}
        mock_subtasks.return_value = [
            {"subtask_id": "1.1", "passes": False},
            {"subtask_id": "1.2", "passes": True},
        ]

        with patch("app.tasks.autonomous.pickup_queries.load_task_execution_readiness") as mock_ready:
            mock_ready.return_value = MagicMock(ready=True, missing_fields=[])
            assert _determine_next_stage("task-1") == "execution"

    @patch("app.tasks.autonomous.pickup_queries.get_subtasks_for_task")
    @patch("app.tasks.autonomous.pickup_queries.get_task_spirit")
    @patch("app.tasks.autonomous.pickup_queries.task_store")
    def test_incomplete_subtasks_missing_plan_contract_returns_planning(
        self, mock_store: MagicMock, mock_spirit: MagicMock, mock_subtasks: MagicMock
    ) -> None:
        from app.tasks.autonomous.pickup import _determine_next_stage

        mock_store.get_task.return_value = {"labels": [], "description": "Add API endpoint"}
        mock_spirit.return_value = {"done_when": ["Endpoint returns 200"]}
        mock_subtasks.return_value = [{"subtask_id": "1.1", "passes": False}]

        with patch("app.tasks.autonomous.pickup_queries.load_task_execution_readiness") as mock_ready:
            mock_ready.return_value = MagicMock(ready=False, missing_fields=["done_when"])
            assert _determine_next_stage("task-1") == "planning"

    @patch("app.tasks.autonomous.pickup_queries.get_subtasks_for_task")
    @patch("app.tasks.autonomous.pickup_queries.get_task_spirit")
    @patch("app.tasks.autonomous.pickup_queries.task_store")
    def test_context_gap_does_not_park_incomplete_subtasks(
        self,
        mock_store: MagicMock,
        mock_spirit: MagicMock,
        mock_subtasks: MagicMock,
    ) -> None:
        from app.tasks.autonomous.pickup import _determine_next_stage

        mock_store.get_task.return_value = {
            "labels": [],
            "description": "Add API endpoint",
        }
        mock_spirit.return_value = {
            "done_when": ["Endpoint returns 200"],
            "context": {
                "subtasks": [{"subtask_id": "1.1"}],
                "planning_signature": "sig-old",
            },
            "plan_status": "draft",
        }
        mock_subtasks.return_value = [{"subtask_id": "1.1", "passes": False}]

        with patch("app.tasks.autonomous.pickup_queries.load_task_execution_readiness") as mock_ready:
            mock_ready.return_value = MagicMock(ready=False, missing_fields=["context"])
            assert _determine_next_stage("task-1") == "execution"

    @patch("app.tasks.autonomous.pickup_queries.get_subtasks_for_task")
    @patch("app.tasks.autonomous.pickup_queries.get_task_spirit")
    @patch("app.tasks.autonomous.pickup_queries.task_store")
    def test_incomplete_subtasks_with_pending_second_opinion_routes_to_execution(
        self, mock_store: MagicMock, mock_spirit: MagicMock, mock_subtasks: MagicMock
    ) -> None:
        from app.tasks.autonomous.pickup import _determine_next_stage

        mock_store.get_task.return_value = {"labels": [], "description": "Add API endpoint"}
        mock_spirit.return_value = {
            "done_when": ["Endpoint returns 200"],
            "context": {"second_opinion": {"status": "pending", "stage": "task_shape"}},
        }
        mock_subtasks.return_value = [{"subtask_id": "1.1", "passes": False}]

        with patch("app.tasks.autonomous.pickup_queries.load_task_execution_readiness") as mock_ready:
            mock_ready.return_value = MagicMock(ready=False, missing_fields=["second_opinion"])
            assert _determine_next_stage("task-1") == "execution"

    @patch("app.tasks.autonomous.pickup_queries.get_subtasks_for_task")
    @patch("app.tasks.autonomous.pickup_queries.get_task_spirit")
    @patch("app.tasks.autonomous.pickup_queries.task_store")
    def test_second_opinion_needs_revision_does_not_park_execution(
        self, mock_store: MagicMock, mock_spirit: MagicMock, mock_subtasks: MagicMock
    ) -> None:
        from app.tasks.autonomous.pickup import _determine_next_stage

        mock_store.get_task.return_value = {"labels": [], "description": "Add API endpoint"}
        mock_spirit.return_value = {
            "done_when": ["Endpoint returns 200"],
            "context": {"second_opinion": {"status": "needs_revision", "stage": "task_shape"}},
        }
        mock_subtasks.return_value = [{"subtask_id": "1.1", "passes": False}]

        with patch("app.tasks.autonomous.pickup_queries.load_task_execution_readiness") as mock_ready:
            mock_ready.return_value = MagicMock(ready=False, missing_fields=["second_opinion"])
            assert _determine_next_stage("task-1") == "execution"

    @patch("app.tasks.autonomous.pickup_queries.get_subtasks_for_task")
    @patch("app.tasks.autonomous.pickup_queries.get_task_spirit")
    @patch("app.tasks.autonomous.pickup_queries.task_store")
    def test_second_opinion_needs_revision_does_not_replan_after_task_shape_changes(
        self,
        mock_store: MagicMock,
        mock_spirit: MagicMock,
        mock_subtasks: MagicMock,
    ) -> None:
        from app.tasks.autonomous.pickup import _determine_next_stage

        mock_store.get_task.return_value = {
            "labels": [],
            "description": "Add API endpoint",
        }
        mock_spirit.return_value = {
            "done_when": ["Endpoint returns 200"],
            "context": {
                "planning_signature": "sig-old",
                "second_opinion": {"status": "needs_revision", "stage": "task_shape"},
            },
        }
        mock_subtasks.return_value = [{"subtask_id": "1.1", "passes": False}]

        with patch("app.tasks.autonomous.pickup_queries.load_task_execution_readiness") as mock_ready:
            mock_ready.return_value = MagicMock(ready=False, missing_fields=["second_opinion"])
            assert _determine_next_stage("task-1") == "execution"

    @patch("app.tasks.autonomous.pickup_queries.get_subtasks_for_task")
    @patch("app.tasks.autonomous.pickup_queries.get_task_spirit")
    @patch("app.tasks.autonomous.pickup_queries.task_store")
    def test_execution_contract_gap_does_not_block_execution(
        self, mock_store: MagicMock, mock_spirit: MagicMock, mock_subtasks: MagicMock
    ) -> None:
        from app.tasks.autonomous.pickup import _determine_next_stage

        mock_store.get_task.return_value = {
            "labels": [],
            "description": "Refresh dashboard layout",
            "updated_at": datetime(2026, 3, 24, 12, 17, 6, tzinfo=UTC),
            "created_at": datetime(2026, 3, 24, 12, 17, 4, tzinfo=UTC),
        }
        mock_spirit.return_value = {
            "done_when": ["Dashboard loads"],
            "context": {
                "subtasks": [{"subtask_id": "1.1"}],
                "planning_signature": "sig-old",
            },
            "updated_at": datetime(2026, 3, 24, 12, 17, 5, tzinfo=UTC).isoformat(),
        }
        mock_subtasks.return_value = [{"subtask_id": "1.1", "passes": False}]

        with patch("app.tasks.autonomous.pickup_queries.load_task_execution_readiness") as mock_ready:
            mock_ready.return_value = MagicMock(ready=False, missing_fields=["execution_contract"])
            assert _determine_next_stage("task-1") == "execution"

    @patch("app.tasks.autonomous.pickup_queries.get_subtasks_for_task")
    @patch("app.tasks.autonomous.pickup_queries.get_task_spirit")
    @patch("app.tasks.autonomous.pickup_queries.task_store")
    def test_all_subtasks_passed_pending_task_routes_to_review(
        self, mock_store: MagicMock, mock_spirit: MagicMock, mock_subtasks: MagicMock
    ) -> None:
        """Pending residue with all subtasks passed → review."""
        from app.tasks.autonomous.pickup import _determine_next_stage

        mock_store.get_task.return_value = {
            "labels": [],
            "description": "Add API endpoint",
            "status": "pending",
        }
        mock_spirit.return_value = {"done_when": ["Endpoint returns 200"]}
        mock_subtasks.return_value = [
            {"subtask_id": "1.1", "passes": True},
        ]

        with patch("app.tasks.autonomous.pickup_queries.load_task_execution_readiness") as mock_ready:
            mock_ready.return_value = MagicMock(ready=True, missing_fields=[])
            assert _determine_next_stage("task-1") == "review"

    @patch("app.tasks.autonomous.pickup_queries.get_subtasks_for_task")
    @patch("app.tasks.autonomous.pickup_queries.get_task_spirit")
    @patch("app.tasks.autonomous.pickup_queries.task_store")
    def test_all_subtasks_passed_completed_task_stays_unknown(
        self, mock_store: MagicMock, mock_spirit: MagicMock, mock_subtasks: MagicMock
    ) -> None:
        from app.tasks.autonomous.pickup import _determine_next_stage

        mock_store.get_task.return_value = {
            "labels": [],
            "description": "Add API endpoint",
            "status": "completed",
        }
        mock_spirit.return_value = {"done_when": ["Endpoint returns 200"]}
        mock_subtasks.return_value = [{"subtask_id": "1.1", "passes": True}]

        with patch("app.tasks.autonomous.pickup_queries.load_task_execution_readiness") as mock_ready:
            mock_ready.return_value = MagicMock(ready=True, missing_fields=[])
            assert _determine_next_stage("task-1") == "unknown"


class TestQueuedAutonomousTasks:
    """Tests for execution-mode filtering in pickup queries."""

    @patch("app.tasks.autonomous.pickup_queries.get_cursor")
    def test_only_autonomous_mode_rows_are_returned(self, mock_get_cursor: MagicMock) -> None:
        from app.tasks.autonomous.pickup_queries import get_queued_autonomous_tasks

        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("task-1", "Auto task", "task", "SIMPLE", "pending"),
        ]
        mock_get_cursor.return_value.__enter__.return_value = mock_cursor

        tasks = get_queued_autonomous_tasks("summitflow")

        sql_text = mock_cursor.execute.call_args.args[0]
        assert "execution_mode = 'autonomous'" in sql_text
        assert "status = 'pending'" in sql_text
        assert "CASE WHEN 'feedback' = ANY(labels) THEN 0 ELSE 1 END" in sql_text
        assert tasks[0]["id"] == "task-1"


# =============================================================================
# T5: Agent routing
# =============================================================================


class TestAgentRouting:
    """Tests for direct agent routing."""

    def test_get_agent_for_subtask_known_types(self) -> None:
        """Known subtask types map to correct agents."""
        from app.tasks.autonomous.exec_modules.agent_routing import get_agent_for_subtask

        assert get_agent_for_subtask("backend") == "coder"
        assert get_agent_for_subtask("refactor") == "refactor"
        assert get_agent_for_subtask("bug-fix") == "debugger"
        assert get_agent_for_subtask("ui-design") == "ux-polisher"

    def test_get_agent_for_subtask_new_types(self) -> None:
        """New subtask types route to correct specialist agents."""
        from app.tasks.autonomous.exec_modules.agent_routing import get_agent_for_subtask

        assert get_agent_for_subtask("database") == "coder"
        assert get_agent_for_subtask("image-gen") == "image-gen"
        assert get_agent_for_subtask("game-design") == "coder"
        assert get_agent_for_subtask("design-review") == "designer"
        assert get_agent_for_subtask("exploration") == "explorer"

    def test_get_agent_for_subtask_falls_back_to_task_type(self) -> None:
        """Unknown subtask type falls back to task_type mapping."""
        from app.tasks.autonomous.exec_modules.agent_routing import get_agent_for_subtask

        result = get_agent_for_subtask("unknown", task_type="bug")
        assert result == "debugger"
        assert get_agent_for_subtask(None, task_type="debt") == "refactor"

    def test_get_agent_for_subtask_routes_generic_bug_work_to_debugger(self) -> None:
        """Bug tasks with generic implementation subtasks should use maintenance agents."""
        from app.tasks.autonomous.exec_modules.agent_routing import get_agent_for_subtask

        assert get_agent_for_subtask("backend", task_type="bug") == "debugger"
        assert get_agent_for_subtask("frontend", task_type="regression") == "debugger"

    def test_get_agent_for_subtask_routes_generic_refactor_work_to_refactor(self) -> None:
        """Refactor/debt tasks with generic subtasks should prefer the refactor agent."""
        from app.tasks.autonomous.exec_modules.agent_routing import get_agent_for_subtask

        assert get_agent_for_subtask("backend", task_type="refactor") == "refactor"
        assert get_agent_for_subtask("database", task_type="debt") == "refactor"

    def test_get_agent_for_subtask_default_agent(self) -> None:
        """Unknown subtask + task type → default agent (coder)."""
        from app.tasks.autonomous.exec_modules.agent_routing import (
            DEFAULT_AGENT,
            get_agent_for_subtask,
        )

        result = get_agent_for_subtask("unknown", task_type="unknown")
        assert result == DEFAULT_AGENT

# =============================================================================
# T8: Memory write points
# =============================================================================


class TestMemoryWrites:
    """Tests for memory_writes.py functions."""

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_save_subtask_learning_clean_pass_skips(self, mock_client: MagicMock) -> None:
        """Clean pass (first attempt) should NOT save learning."""
        from app.tasks.autonomous.exec_modules.memory_writes import (
            save_subtask_learning,
        )

        save_subtask_learning(
            task_id="task-1",
            subtask_short_id="1.1",
            subtask_type="backend",
            project_id="test-project",
            passed=True,
            self_fix_attempts=0,
            supervisor_guided_attempts=0,
            step_results=[],
        )

        mock_client.return_value.save_learning.assert_not_called()

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_save_subtask_learning_passed_with_retries(self, mock_client: MagicMock) -> None:
        """Passed subtask that required retries → save learning with issues."""
        from app.tasks.autonomous.exec_modules.memory_writes import (
            save_subtask_learning,
        )

        save_subtask_learning(
            task_id="task-1",
            subtask_short_id="1.1",
            subtask_type="backend",
            project_id="test-project",
            passed=True,
            self_fix_attempts=2,
            supervisor_guided_attempts=1,
            step_results=[
                {"step_number": 1, "status": "failed", "reason": "missing import"},
                {"step_number": 2, "status": "passed"},
            ],
        )

        mock_client.return_value.save_learning.assert_called_once()
        call_kwargs = mock_client.return_value.save_learning.call_args
        content = call_kwargs[1].get("content") or call_kwargs[0][0]
        assert "1.1" in content
        assert "reference" in str(call_kwargs)

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_save_subtask_learning_failed(self, mock_client: MagicMock) -> None:
        """Failed subtask → save learning with failure info."""
        from app.tasks.autonomous.exec_modules.memory_writes import (
            save_subtask_learning,
        )

        save_subtask_learning(
            task_id="task-1",
            subtask_short_id="1.1",
            subtask_type="backend",
            project_id="test-project",
            passed=False,
            self_fix_attempts=3,
            supervisor_guided_attempts=3,
            step_results=[
                {"step_number": 1, "status": "failed", "reason": "compilation error"},
            ],
        )

        mock_client.return_value.save_learning.assert_called_once()
        call_kwargs = mock_client.return_value.save_learning.call_args
        content = call_kwargs[1].get("content") or call_kwargs[0][0]
        assert "FAILED" in content

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_save_qa_fix_pattern(self, mock_client: MagicMock) -> None:
        """QA fix pattern → save learning with correct content."""
        from app.tasks.autonomous.exec_modules.memory_writes import (
            save_qa_fix_pattern,
        )

        save_qa_fix_pattern(
            task_id="task-1",
            project_id="test-project",
            concern="Missing error handling",
            fix_iteration=2,
        )

        mock_client.return_value.save_learning.assert_called_once()
        call_kwargs = mock_client.return_value.save_learning.call_args
        content = call_kwargs[1].get("content") or call_kwargs[0][0]
        assert "QA fix pattern" in content
        assert "Missing error handling" in content

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_rate_cited_memories(self, mock_client: MagicMock) -> None:
        """Rate cited memories → calls rate_episode for each UUID."""
        from app.tasks.autonomous.exec_modules.memory_writes import rate_cited_memories

        rate_cited_memories(["uuid-1", "uuid-2", "uuid-3"])

        assert mock_client.return_value.rate_episode.call_count == 3
        mock_client.return_value.rate_episode.assert_any_call("uuid-1", "helpful")
        mock_client.return_value.rate_episode.assert_any_call("uuid-2", "helpful")
        mock_client.return_value.rate_episode.assert_any_call("uuid-3", "helpful")

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_rate_cited_memories_empty_list(self, mock_client: MagicMock) -> None:
        """Empty cited UUIDs → no API calls."""
        from app.tasks.autonomous.exec_modules.memory_writes import rate_cited_memories

        rate_cited_memories([])

        mock_client.assert_not_called()

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_rate_cited_memories_caps_at_10(self, mock_client: MagicMock) -> None:
        """More than 10 UUIDs → only first 10 are rated."""
        from app.tasks.autonomous.exec_modules.memory_writes import rate_cited_memories

        uuids = [f"uuid-{i}" for i in range(15)]
        rate_cited_memories(uuids)

        assert mock_client.return_value.rate_episode.call_count == 10

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_save_subtask_learning_handles_exception(self, mock_client: MagicMock) -> None:
        """Exception in save_learning should NOT propagate."""
        from app.tasks.autonomous.exec_modules.memory_writes import (
            save_subtask_learning,
        )

        mock_client.return_value.save_learning.side_effect = Exception("API error")

        # Should not raise
        save_subtask_learning(
            task_id="task-1",
            subtask_short_id="1.1",
            subtask_type="backend",
            project_id="test-project",
            passed=False,
            self_fix_attempts=1,
            supervisor_guided_attempts=0,
            step_results=[{"step_number": 1, "status": "failed", "reason": "err"}],
        )

    @patch("app.tasks.autonomous.exec_modules.memory_writes.get_sync_client")
    def test_rate_cited_memories_handles_exception(self, mock_client: MagicMock) -> None:
        """Exception in rate_episode should NOT propagate."""
        from app.tasks.autonomous.exec_modules.memory_writes import rate_cited_memories

        mock_client.return_value.rate_episode.side_effect = Exception("API error")

        # Should not raise
        rate_cited_memories(["uuid-1", "uuid-2"])


# =============================================================================
# T9: Resume context builder
# =============================================================================


class TestResumeContext:
    """Tests for build_resume_context in prompts.py."""

    @patch("app.tasks.autonomous.exec_modules.prompts.get_events_by_trace")
    def test_no_events_returns_empty(self, mock_events: MagicMock) -> None:
        """No prior events → empty string."""
        from app.tasks.autonomous.exec_modules.prompts import build_resume_context

        mock_events.return_value = []

        result = build_resume_context("task-1")
        assert result == ""

    @patch("app.tasks.autonomous.exec_modules.prompts.get_events_by_trace")
    def test_with_failure_events_returns_context(self, mock_events: MagicMock) -> None:
        """Prior failure events → resume context with failure summary."""
        from app.tasks.autonomous.exec_modules.prompts import build_resume_context

        mock_events.return_value = [
            {"message": "Starting execution", "level": "info"},
            {"message": "Step FAILED: missing import", "level": "error"},
            {"message": "Subtask FAILED after 3 attempts", "level": "warn"},
        ]

        result = build_resume_context("task-1")
        assert "Resume Context" in result
        assert "FAILED" in result

    @patch("app.tasks.autonomous.exec_modules.prompts.get_events_by_trace")
    def test_with_session_end_events(self, mock_events: MagicMock) -> None:
        """SESSION END events → resume context with session state."""
        from app.tasks.autonomous.exec_modules.prompts import build_resume_context

        mock_events.return_value = [
            {"message": "SESSION END: completed 2/3 subtasks", "level": "info"},
        ]

        result = build_resume_context("task-1")
        assert "Resume Context" in result
        assert "SESSION END" in result

    @patch("app.tasks.autonomous.exec_modules.prompts.get_events_by_trace")
    def test_no_relevant_events_returns_empty(self, mock_events: MagicMock) -> None:
        """Events without SESSION END or FAILED → empty string."""
        from app.tasks.autonomous.exec_modules.prompts import build_resume_context

        mock_events.return_value = [
            {"message": "Starting execution", "level": "info"},
            {"message": "Step passed", "level": "info"},
        ]

        result = build_resume_context("task-1")
        assert result == ""

    @patch("app.tasks.autonomous.exec_modules.prompts.get_events_by_trace")
    def test_exception_returns_empty(self, mock_events: MagicMock) -> None:
        """Exception in event query → empty string (no propagation)."""
        from app.tasks.autonomous.exec_modules.prompts import build_resume_context

        mock_events.side_effect = Exception("DB error")

        result = build_resume_context("task-1")
        assert result == ""
