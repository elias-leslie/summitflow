"""Task Lifecycle State Machine for Git Management.

Defines the states and transitions for agent-driven git workflows:
  pending → running → pr_created → ai_reviewing → completed
                                 ↓
                            human_review

Supports both human workflows (direct on main) and agent workflows
(worktree isolation with AI-reviewed auto-merge).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class TaskLifecycleState(str, Enum):
    """Task lifecycle states for git management workflow."""

    # Initial state
    pending = "pending"

    # Work states
    running = "running"
    failed = "failed"
    blocked = "blocked"

    # PR/Review states
    pr_created = "pr_created"
    ai_reviewing = "ai_reviewing"
    human_review = "human_review"

    # Terminal states
    completed = "completed"
    cancelled = "cancelled"

    @classmethod
    def terminal_states(cls) -> set[TaskLifecycleState]:
        """States that represent end of lifecycle."""
        return {cls.completed, cls.cancelled}

    @classmethod
    def active_states(cls) -> set[TaskLifecycleState]:
        """States where work is in progress."""
        return {cls.running, cls.ai_reviewing}

    @classmethod
    def review_states(cls) -> set[TaskLifecycleState]:
        """States where review is needed."""
        return {cls.pr_created, cls.ai_reviewing, cls.human_review}

    @classmethod
    def can_retry(cls) -> set[TaskLifecycleState]:
        """States that allow retry."""
        return {cls.failed, cls.blocked}


VALID_TRANSITIONS: dict[TaskLifecycleState, set[TaskLifecycleState]] = {
    TaskLifecycleState.pending: {
        TaskLifecycleState.running,
        TaskLifecycleState.blocked,
        TaskLifecycleState.cancelled,
    },
    TaskLifecycleState.running: {
        TaskLifecycleState.pr_created,
        TaskLifecycleState.failed,
        TaskLifecycleState.blocked,
        TaskLifecycleState.cancelled,
    },
    TaskLifecycleState.failed: {
        TaskLifecycleState.pending,  # Retry
        TaskLifecycleState.running,  # Direct retry
        TaskLifecycleState.cancelled,
    },
    TaskLifecycleState.blocked: {
        TaskLifecycleState.pending,  # Unblock
        TaskLifecycleState.running,  # Direct resume
        TaskLifecycleState.cancelled,
    },
    TaskLifecycleState.pr_created: {
        TaskLifecycleState.ai_reviewing,
        TaskLifecycleState.human_review,  # Skip AI review
        TaskLifecycleState.failed,
        TaskLifecycleState.cancelled,
    },
    TaskLifecycleState.ai_reviewing: {
        TaskLifecycleState.completed,  # Auto-merge on pass
        TaskLifecycleState.human_review,  # Escalate
        TaskLifecycleState.running,  # Retry with fixes
        TaskLifecycleState.failed,
    },
    TaskLifecycleState.human_review: {
        TaskLifecycleState.completed,  # Approved
        TaskLifecycleState.running,  # Changes requested
        TaskLifecycleState.cancelled,
    },
    # Terminal states - no transitions out
    TaskLifecycleState.completed: set(),
    TaskLifecycleState.cancelled: set(),
}


class ConflictType(str, Enum):
    """Types of conflicts that can occur during state transitions."""

    INVALID_TRANSITION = "invalid_transition"
    CONCURRENT_OPERATION = "concurrent_operation"
    STALE_STATE = "stale_state"
    LOCKED = "locked"


@dataclass
class ConflictResult:
    """Result of a conflict check or transition attempt."""

    has_conflict: bool
    conflict_type: ConflictType | None = None
    message: str = ""
    blocking_state: TaskLifecycleState | None = None
    resolution_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_conflict": self.has_conflict,
            "conflict_type": self.conflict_type.value if self.conflict_type else None,
            "message": self.message,
            "blocking_state": self.blocking_state.value if self.blocking_state else None,
            "resolution_hint": self.resolution_hint,
        }


@dataclass
class StateTransition:
    """Record of a state transition for history tracking."""

    from_state: TaskLifecycleState
    to_state: TaskLifecycleState
    timestamp: str
    actor: str
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "timestamp": self.timestamp,
            "actor": self.actor,
            "reason": self.reason,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StateTransition:
        return cls(
            from_state=TaskLifecycleState(data["from_state"]),
            to_state=TaskLifecycleState(data["to_state"]),
            timestamp=data["timestamp"],
            actor=data["actor"],
            reason=data.get("reason"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class TaskLifecycle:
    """Lifecycle state for a single task with git workflow support."""

    task_id: str
    current_state: TaskLifecycleState = TaskLifecycleState.pending
    transitions: list[StateTransition] = field(default_factory=list)
    locked_by: str | None = None
    locked_at: str | None = None
    lock_expires_at: str | None = None
    pr_url: str | None = None
    branch_name: str | None = None
    worktree_path: str | None = None
    review_result: dict[str, Any] | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def can_transition_to(self, new_state: TaskLifecycleState) -> bool:
        """Check if transition to new_state is valid."""
        valid = VALID_TRANSITIONS.get(self.current_state, set())
        return new_state in valid

    def is_locked(self) -> bool:
        """Check if lifecycle is currently locked."""
        if not self.locked_by or not self.lock_expires_at:
            return False
        try:
            expires = datetime.fromisoformat(self.lock_expires_at)
            return datetime.now(UTC) < expires
        except (ValueError, TypeError):
            return False

    def acquire_lock(
        self,
        actor: str,
        duration_seconds: int = 300,
    ) -> ConflictResult:
        """Acquire lock for concurrent operation prevention.

        Args:
            actor: Identifier for who is acquiring the lock
            duration_seconds: Lock duration (default 5 minutes)

        Returns:
            ConflictResult indicating success or conflict
        """
        if self.is_locked() and self.locked_by != actor:
            return ConflictResult(
                has_conflict=True,
                conflict_type=ConflictType.LOCKED,
                message=f"Task locked by {self.locked_by}",
                resolution_hint=f"Wait until lock expires at {self.lock_expires_at}",
            )

        now = datetime.now(UTC)
        self.locked_by = actor
        self.locked_at = now.isoformat()
        from datetime import timedelta

        self.lock_expires_at = (now + timedelta(seconds=duration_seconds)).isoformat()
        self.updated_at = now.isoformat()

        return ConflictResult(has_conflict=False)

    def release_lock(self, actor: str) -> ConflictResult:
        """Release lock held by actor.

        Args:
            actor: Identifier for who is releasing the lock

        Returns:
            ConflictResult indicating success or conflict
        """
        if self.locked_by and self.locked_by != actor:
            return ConflictResult(
                has_conflict=True,
                conflict_type=ConflictType.LOCKED,
                message=f"Cannot release lock held by {self.locked_by}",
                resolution_hint="Only the lock holder can release the lock",
            )

        self.locked_by = None
        self.locked_at = None
        self.lock_expires_at = None
        self.updated_at = datetime.now(UTC).isoformat()

        return ConflictResult(has_conflict=False)

    def transition(
        self,
        new_state: TaskLifecycleState,
        actor: str,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
        force: bool = False,
    ) -> ConflictResult:
        """Attempt to transition to a new state.

        Args:
            new_state: Target state
            actor: Identifier for who is making the transition
            reason: Optional reason for transition
            metadata: Optional metadata to attach to transition
            force: Skip validation (use with caution)

        Returns:
            ConflictResult indicating success or conflict
        """
        # Check lock
        if self.is_locked() and self.locked_by != actor:
            return ConflictResult(
                has_conflict=True,
                conflict_type=ConflictType.CONCURRENT_OPERATION,
                message=f"Task locked by {self.locked_by}",
                resolution_hint="Wait for lock to expire or be released",
            )

        # Validate transition
        if not force and not self.can_transition_to(new_state):
            valid = VALID_TRANSITIONS.get(self.current_state, set())
            return ConflictResult(
                has_conflict=True,
                conflict_type=ConflictType.INVALID_TRANSITION,
                message=f"Cannot transition from {self.current_state.value} to {new_state.value}",
                blocking_state=self.current_state,
                resolution_hint=f"Valid transitions: {[s.value for s in valid]}",
            )

        # Record transition
        transition = StateTransition(
            from_state=self.current_state,
            to_state=new_state,
            timestamp=datetime.now(UTC).isoformat(),
            actor=actor,
            reason=reason,
            metadata=metadata or {},
        )
        self.transitions.append(transition)
        self.current_state = new_state
        self.updated_at = datetime.now(UTC).isoformat()

        return ConflictResult(has_conflict=False)

    def get_transition_history(self) -> list[dict[str, Any]]:
        """Get list of all state transitions."""
        return [t.to_dict() for t in self.transitions]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "task_id": self.task_id,
            "current_state": self.current_state.value,
            "transitions": self.get_transition_history(),
            "locked_by": self.locked_by,
            "locked_at": self.locked_at,
            "lock_expires_at": self.lock_expires_at,
            "pr_url": self.pr_url,
            "branch_name": self.branch_name,
            "worktree_path": self.worktree_path,
            "review_result": self.review_result,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskLifecycle:
        """Deserialize from dictionary."""
        lifecycle = cls(
            task_id=data["task_id"],
            current_state=TaskLifecycleState(data.get("current_state", "pending")),
            locked_by=data.get("locked_by"),
            locked_at=data.get("locked_at"),
            lock_expires_at=data.get("lock_expires_at"),
            pr_url=data.get("pr_url"),
            branch_name=data.get("branch_name"),
            worktree_path=data.get("worktree_path"),
            review_result=data.get("review_result"),
            created_at=data.get("created_at", datetime.now(UTC).isoformat()),
            updated_at=data.get("updated_at", datetime.now(UTC).isoformat()),
        )
        # Restore transitions
        for t in data.get("transitions", []):
            lifecycle.transitions.append(StateTransition.from_dict(t))
        return lifecycle


def validate_transition(current: str, target: str) -> bool:
    """Check if a status transition is valid.

    Args:
        current: Current state value
        target: Target state value

    Returns:
        True if transition is valid
    """
    try:
        current_state = TaskLifecycleState(current)
        target_state = TaskLifecycleState(target)
        return target_state in VALID_TRANSITIONS.get(current_state, set())
    except ValueError:
        return False


def get_valid_transitions(current: str) -> list[str]:
    """Get list of valid transitions from current state.

    Args:
        current: Current state value

    Returns:
        List of valid target state values
    """
    try:
        current_state = TaskLifecycleState(current)
        valid = VALID_TRANSITIONS.get(current_state, set())
        return [s.value for s in valid]
    except ValueError:
        return []
