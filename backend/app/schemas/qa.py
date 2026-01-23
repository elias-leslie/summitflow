"""QA review schemas for task quality verification.

These models track the state of QA review loops, including:
- Issues encountered during execution
- QA attempts (worker or supervisor)
- Escalation state and thresholds
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class QAAgent(str, Enum):
    """Agent types for QA review."""

    WORKER = "worker"
    SUPERVISOR = "supervisor"
    QA = "qa"  # The actual QA agent for assessment


class QAVerdict(str, Enum):
    """QA review verdicts."""

    APPROVED = "APPROVED"
    NEEDS_FIX = "NEEDS_FIX"
    PLAN_DEFECT = "PLAN_DEFECT"
    ESCALATE = "ESCALATE"


class Issue(BaseModel):
    """A tracked issue during QA review.

    Issues are identified by their issue_id (computed from error similarity).
    Tracking the same issue across attempts allows for stuck detection.
    """

    issue_id: str = Field(description="Stable ID for this issue (from compute_issue_id)")
    error_message: str = Field(description="The original error message")
    normalized_error: str = Field(description="Normalized error for comparison")
    first_seen: datetime = Field(default_factory=datetime.now)
    last_seen: datetime = Field(default_factory=datetime.now)
    attempt_count: int = Field(default=1, ge=1)
    step_number: int | None = Field(default=None, description="The step where this occurred")
    verify_command: str | None = Field(default=None)
    fix_attempts: list[str] = Field(
        default_factory=list, description="Brief summaries of fix attempts"
    )


class QAAttempt(BaseModel):
    """A single QA review attempt.

    Tracks which agent performed the review and the outcome.
    """

    agent: QAAgent = Field(description="Which agent performed this attempt")
    verdict: QAVerdict = Field(description="The verdict from this attempt")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the verdict")
    summary: str = Field(description="Brief summary of findings")
    issues: list[dict[str, Any]] = Field(default_factory=list)
    plan_defect: dict[str, Any] | None = Field(default=None)
    timestamp: datetime = Field(default_factory=datetime.now)


class QAState(BaseModel):
    """State of the QA review loop for a subtask.

    Tracks all issues encountered, attempts made, and escalation state.
    """

    subtask_id: str = Field(description="The subtask being reviewed")
    issues: dict[str, Issue] = Field(default_factory=dict, description="Issues by issue_id")
    attempts: list[QAAttempt] = Field(default_factory=list)
    worker_stuck_count: int = Field(
        default=0, ge=0, description="Consecutive worker failures on same issue"
    )
    supervisor_stuck_count: int = Field(
        default=0, ge=0, description="Consecutive supervisor failures"
    )
    total_attempts: int = Field(default=0, ge=0)
    escalated: bool = Field(default=False, description="Whether this has been escalated to human")
    escalation_reason: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    def add_issue(self, issue: Issue) -> None:
        """Add or update an issue in the state."""
        if issue.issue_id in self.issues:
            existing = self.issues[issue.issue_id]
            existing.attempt_count += 1
            existing.last_seen = datetime.now()
        else:
            self.issues[issue.issue_id] = issue
        self.updated_at = datetime.now()

    def add_attempt(self, attempt: QAAttempt) -> None:
        """Add a QA attempt and update counters."""
        self.attempts.append(attempt)
        self.total_attempts += 1
        self.updated_at = datetime.now()

    def should_escalate_to_supervisor(self, threshold: int) -> bool:
        """Check if we should escalate from worker to supervisor."""
        return self.worker_stuck_count >= threshold

    def should_escalate_to_human(self, threshold: int) -> bool:
        """Check if we should escalate to human review."""
        return self.supervisor_stuck_count >= threshold or self.total_attempts >= threshold
