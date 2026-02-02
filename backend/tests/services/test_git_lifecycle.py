"""Unit tests for git_lifecycle state machine."""

from app.services.git_lifecycle import (
    VALID_TRANSITIONS,
    ConflictResult,
    ConflictType,
    StateTransition,
    TaskLifecycle,
    TaskLifecycleState,
    get_valid_transitions,
    validate_transition,
)


class TestTaskLifecycleState:
    """Tests for TaskLifecycleState enum."""

    def test_has_10_states(self):
        """Verify exactly 10 states exist (including abandoned)."""
        states = list(TaskLifecycleState)
        assert len(states) == 10
        expected = {
            "pending",
            "running",
            "failed",
            "blocked",
            "pr_created",
            "ai_reviewing",
            "human_review",
            "completed",
            "cancelled",
            "abandoned",
        }
        actual = {s.value for s in states}
        assert actual == expected

    def test_terminal_states(self):
        """Verify terminal states are completed and cancelled."""
        terminal = TaskLifecycleState.terminal_states()
        assert terminal == {TaskLifecycleState.completed, TaskLifecycleState.cancelled}

    def test_active_states(self):
        """Verify active states are running and ai_reviewing."""
        active = TaskLifecycleState.active_states()
        assert active == {TaskLifecycleState.running, TaskLifecycleState.ai_reviewing}

    def test_review_states(self):
        """Verify review states include PR and review states."""
        review = TaskLifecycleState.review_states()
        assert review == {
            TaskLifecycleState.pr_created,
            TaskLifecycleState.ai_reviewing,
            TaskLifecycleState.human_review,
        }

    def test_can_retry_states(self):
        """Verify retry states are failed and blocked."""
        retry = TaskLifecycleState.can_retry()
        assert retry == {TaskLifecycleState.failed, TaskLifecycleState.blocked}


class TestValidTransitions:
    """Tests for VALID_TRANSITIONS mapping."""

    def test_pending_transitions(self):
        """Pending can go to running, blocked, or cancelled."""
        valid = VALID_TRANSITIONS[TaskLifecycleState.pending]
        assert valid == {
            TaskLifecycleState.running,
            TaskLifecycleState.blocked,
            TaskLifecycleState.cancelled,
        }

    def test_running_transitions(self):
        """Running can go to pr_created, failed, blocked, or cancelled."""
        valid = VALID_TRANSITIONS[TaskLifecycleState.running]
        assert valid == {
            TaskLifecycleState.pr_created,
            TaskLifecycleState.failed,
            TaskLifecycleState.blocked,
            TaskLifecycleState.cancelled,
        }

    def test_ai_reviewing_transitions(self):
        """AI reviewing can go to completed, human_review, running, or failed."""
        valid = VALID_TRANSITIONS[TaskLifecycleState.ai_reviewing]
        assert valid == {
            TaskLifecycleState.completed,
            TaskLifecycleState.human_review,
            TaskLifecycleState.running,
            TaskLifecycleState.failed,
        }

    def test_terminal_states_no_transitions(self):
        """Terminal states have no valid transitions."""
        assert VALID_TRANSITIONS[TaskLifecycleState.completed] == set()
        assert VALID_TRANSITIONS[TaskLifecycleState.cancelled] == set()

    def test_all_states_have_transitions_defined(self):
        """Every state should have an entry in VALID_TRANSITIONS."""
        for state in TaskLifecycleState:
            assert state in VALID_TRANSITIONS


class TestValidateTransition:
    """Tests for validate_transition helper function."""

    def test_valid_transition(self):
        """Valid transition returns True."""
        assert validate_transition("pending", "running") is True
        assert validate_transition("running", "pr_created") is True
        assert validate_transition("ai_reviewing", "completed") is True

    def test_invalid_transition(self):
        """Invalid transition returns False."""
        assert validate_transition("pending", "completed") is False
        assert validate_transition("completed", "running") is False
        assert validate_transition("cancelled", "pending") is False

    def test_invalid_state_values(self):
        """Invalid state values return False."""
        assert validate_transition("invalid", "running") is False
        assert validate_transition("pending", "invalid") is False


class TestGetValidTransitions:
    """Tests for get_valid_transitions helper function."""

    def test_returns_valid_transitions(self):
        """Returns list of valid target states."""
        valid = get_valid_transitions("pending")
        assert set(valid) == {"running", "blocked", "cancelled"}

    def test_invalid_state_returns_empty(self):
        """Invalid state returns empty list."""
        assert get_valid_transitions("invalid") == []


class TestTaskLifecycle:
    """Tests for TaskLifecycle dataclass."""

    def test_create_lifecycle(self):
        """Create lifecycle with default state."""
        lifecycle = TaskLifecycle(task_id="task-123")
        assert lifecycle.task_id == "task-123"
        assert lifecycle.current_state == TaskLifecycleState.pending
        assert lifecycle.transitions == []
        assert lifecycle.locked_by is None

    def test_can_transition_to_valid(self):
        """can_transition_to returns True for valid transitions."""
        lifecycle = TaskLifecycle(task_id="task-123")
        assert lifecycle.can_transition_to(TaskLifecycleState.running) is True
        assert lifecycle.can_transition_to(TaskLifecycleState.cancelled) is True

    def test_can_transition_to_invalid(self):
        """can_transition_to returns False for invalid transitions."""
        lifecycle = TaskLifecycle(task_id="task-123")
        assert lifecycle.can_transition_to(TaskLifecycleState.completed) is False
        assert lifecycle.can_transition_to(TaskLifecycleState.ai_reviewing) is False

    def test_transition_success(self):
        """Successful transition updates state and records history."""
        lifecycle = TaskLifecycle(task_id="task-123")
        result = lifecycle.transition(
            TaskLifecycleState.running, actor="agent-1", reason="Starting work"
        )
        assert result.has_conflict is False
        assert lifecycle.current_state == TaskLifecycleState.running
        assert len(lifecycle.transitions) == 1
        assert lifecycle.transitions[0].from_state == TaskLifecycleState.pending
        assert lifecycle.transitions[0].to_state == TaskLifecycleState.running
        assert lifecycle.transitions[0].actor == "agent-1"
        assert lifecycle.transitions[0].reason == "Starting work"

    def test_transition_invalid(self):
        """Invalid transition returns conflict result."""
        lifecycle = TaskLifecycle(task_id="task-123")
        result = lifecycle.transition(TaskLifecycleState.completed, actor="agent-1")
        assert result.has_conflict is True
        assert result.conflict_type == ConflictType.INVALID_TRANSITION
        assert lifecycle.current_state == TaskLifecycleState.pending
        assert len(lifecycle.transitions) == 0

    def test_transition_force(self):
        """Force flag allows invalid transitions."""
        lifecycle = TaskLifecycle(task_id="task-123")
        result = lifecycle.transition(TaskLifecycleState.completed, actor="admin", force=True)
        assert result.has_conflict is False
        assert lifecycle.current_state == TaskLifecycleState.completed


class TestTaskLifecycleLocking:
    """Tests for TaskLifecycle locking mechanism."""

    def test_acquire_lock_success(self):
        """Acquiring lock on unlocked lifecycle succeeds."""
        lifecycle = TaskLifecycle(task_id="task-123")
        result = lifecycle.acquire_lock("agent-1", duration_seconds=60)
        assert result.has_conflict is False
        assert lifecycle.locked_by == "agent-1"
        assert lifecycle.is_locked() is True

    def test_acquire_lock_same_actor(self):
        """Same actor can re-acquire lock."""
        lifecycle = TaskLifecycle(task_id="task-123")
        lifecycle.acquire_lock("agent-1")
        result = lifecycle.acquire_lock("agent-1")
        assert result.has_conflict is False

    def test_acquire_lock_different_actor(self):
        """Different actor cannot acquire existing lock."""
        lifecycle = TaskLifecycle(task_id="task-123")
        lifecycle.acquire_lock("agent-1")
        result = lifecycle.acquire_lock("agent-2")
        assert result.has_conflict is True
        assert result.conflict_type == ConflictType.LOCKED

    def test_release_lock_success(self):
        """Lock holder can release lock."""
        lifecycle = TaskLifecycle(task_id="task-123")
        lifecycle.acquire_lock("agent-1")
        result = lifecycle.release_lock("agent-1")
        assert result.has_conflict is False
        assert lifecycle.is_locked() is False

    def test_release_lock_wrong_actor(self):
        """Non-holder cannot release lock."""
        lifecycle = TaskLifecycle(task_id="task-123")
        lifecycle.acquire_lock("agent-1")
        result = lifecycle.release_lock("agent-2")
        assert result.has_conflict is True
        assert result.conflict_type == ConflictType.LOCKED

    def test_transition_blocked_by_lock(self):
        """Transition fails when locked by another actor."""
        lifecycle = TaskLifecycle(task_id="task-123")
        lifecycle.acquire_lock("agent-1")
        result = lifecycle.transition(TaskLifecycleState.running, actor="agent-2")
        assert result.has_conflict is True
        assert result.conflict_type == ConflictType.CONCURRENT_OPERATION

    def test_transition_allowed_by_lock_holder(self):
        """Lock holder can transition."""
        lifecycle = TaskLifecycle(task_id="task-123")
        lifecycle.acquire_lock("agent-1")
        result = lifecycle.transition(TaskLifecycleState.running, actor="agent-1")
        assert result.has_conflict is False


class TestTaskLifecycleSerialization:
    """Tests for TaskLifecycle serialization."""

    def test_to_dict(self):
        """to_dict returns complete representation."""
        lifecycle = TaskLifecycle(task_id="task-123")
        lifecycle.transition(TaskLifecycleState.running, actor="agent-1")
        data = lifecycle.to_dict()
        assert data["task_id"] == "task-123"
        assert data["current_state"] == "running"
        assert len(data["transitions"]) == 1

    def test_from_dict(self):
        """from_dict restores lifecycle state."""
        original = TaskLifecycle(task_id="task-123")
        original.transition(TaskLifecycleState.running, actor="agent-1")
        data = original.to_dict()
        restored = TaskLifecycle.from_dict(data)
        assert restored.task_id == original.task_id
        assert restored.current_state == original.current_state
        assert len(restored.transitions) == len(original.transitions)


class TestStateTransition:
    """Tests for StateTransition dataclass."""

    def test_to_dict(self):
        """to_dict returns serializable representation."""
        transition = StateTransition(
            from_state=TaskLifecycleState.pending,
            to_state=TaskLifecycleState.running,
            timestamp="2026-01-10T12:00:00Z",
            actor="agent-1",
            reason="Starting",
        )
        data = transition.to_dict()
        assert data["from_state"] == "pending"
        assert data["to_state"] == "running"
        assert data["actor"] == "agent-1"

    def test_from_dict(self):
        """from_dict restores transition."""
        data = {
            "from_state": "pending",
            "to_state": "running",
            "timestamp": "2026-01-10T12:00:00Z",
            "actor": "agent-1",
            "reason": "Starting",
            "metadata": {},
        }
        transition = StateTransition.from_dict(data)
        assert transition.from_state == TaskLifecycleState.pending
        assert transition.to_state == TaskLifecycleState.running


class TestConflictResult:
    """Tests for ConflictResult dataclass."""

    def test_no_conflict(self):
        """No conflict result."""
        result = ConflictResult(has_conflict=False)
        assert result.has_conflict is False
        assert result.conflict_type is None

    def test_with_conflict(self):
        """Conflict result with details."""
        result = ConflictResult(
            has_conflict=True,
            conflict_type=ConflictType.INVALID_TRANSITION,
            message="Cannot transition",
            blocking_state=TaskLifecycleState.pending,
        )
        assert result.has_conflict is True
        data = result.to_dict()
        assert data["conflict_type"] == "invalid_transition"
        assert data["blocking_state"] == "pending"
