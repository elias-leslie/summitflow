"""Recovery Manager - Orchestrates failure recovery.

Manages build state, tracks attempts, and determines recovery strategies.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ...logging_config import get_logger
from ...storage import agent_sessions as sessions_storage
from .circular import is_circular_fix
from .classifier import FailureType, RecoveryStrategy, get_recovery_strategy

logger = get_logger(__name__)


class RecoveryManager:
    """Manages recovery state for a TDD build session.

    Tracks attempt history, good commits, and determines appropriate
    recovery strategies based on failure patterns.
    """

    def __init__(
        self,
        project_id: str,
        session_id: str,
    ) -> None:
        """Initialize RecoveryManager.

        Args:
            project_id: Project ID
            session_id: Build session ID
        """
        self.project_id = project_id
        self.session_id = session_id

        # Load existing state from database
        self._state = sessions_storage.get_build_state(project_id, session_id)

        # Initialize default state if needed
        if not self._state:
            self._state = {
                "attempt_history": [],
                "good_commits": [],
                "current_strategy": RecoveryStrategy.RETRY.value,
            }
            self._save_state()

    @property
    def attempt_count(self) -> int:
        """Get the current attempt count."""
        return len(self._state.get("attempt_history", []))

    @property
    def good_commits(self) -> list[str]:
        """Get list of known good commit SHAs."""
        return list(self._state.get("good_commits", []))

    @property
    def last_good_commit(self) -> str | None:
        """Get the most recent good commit SHA."""
        commits = self.good_commits
        return commits[-1] if commits else None

    def record_attempt(
        self,
        capability_id: str,
        failure_type: FailureType,
        error_text: str,
        commit_sha: str | None = None,
    ) -> dict[str, Any]:
        """Record a build attempt.

        Args:
            capability_id: Capability being built
            failure_type: Type of failure
            error_text: Error message/output
            commit_sha: Current commit SHA (if known)

        Returns:
            The recorded attempt dict.
        """
        attempt = {
            "attempt_number": self.attempt_count + 1,
            "capability_id": capability_id,
            "failure_type": failure_type.value,
            "error_text": error_text[:500],  # Truncate for storage
            "commit_sha": commit_sha,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        history: list[dict[str, Any]] = self._state.setdefault("attempt_history", [])  # type: ignore[assignment]
        history.append(attempt)
        self._save_state()

        logger.info(
            "recorded_attempt",
            attempt_number=attempt["attempt_number"],
            capability_id=capability_id,
            failure_type=failure_type.value,
        )

        return attempt

    def get_recovery_strategy(
        self,
        failure_type: FailureType,
        error_text: str,
    ) -> RecoveryStrategy:
        """Get the recommended recovery strategy.

        Considers failure type, attempt count, and circular fix detection.

        Args:
            failure_type: Type of failure
            error_text: Current error text

        Returns:
            RecoveryStrategy enum value.
        """
        # Check for circular fix
        previous_errors = [
            a["error_text"] for a in self._state.get("attempt_history", []) if "error_text" in a
        ]
        is_circular = is_circular_fix(error_text, previous_errors)

        if is_circular:
            logger.warning("circular_fix_detected", session_id=self.session_id)
            self._state["current_strategy"] = RecoveryStrategy.ESCALATE.value
            self._save_state()
            return RecoveryStrategy.ESCALATE

        # Get strategy based on type and count
        strategy = get_recovery_strategy(
            failure_type=failure_type,
            attempt_count=self.attempt_count,
            is_circular=False,
        )

        self._state["current_strategy"] = strategy.value
        self._save_state()

        return strategy

    def mark_good_commit(self, commit_sha: str) -> None:
        """Mark a commit as known good (tests passed).

        Args:
            commit_sha: Git commit SHA
        """
        if commit_sha and commit_sha not in self.good_commits:
            commits: list[str] = self._state.setdefault("good_commits", [])  # type: ignore[assignment]
            commits.append(commit_sha)
            self._save_state()
            logger.info("marked_good_commit", commit_sha=commit_sha)

    def clear_attempt_history(self) -> None:
        """Clear attempt history (after successful build)."""
        self._state["attempt_history"] = []
        self._save_state()

    def get_attempt_history(
        self,
        capability_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get attempt history, optionally filtered by capability.

        Args:
            capability_id: Optional capability to filter by

        Returns:
            List of attempt dicts.
        """
        history: list[dict[str, Any]] = self._state.get("attempt_history", [])  # type: ignore[assignment]

        if capability_id:
            return [a for a in history if a.get("capability_id") == capability_id]

        return list(history)

    def _save_state(self) -> None:
        """Persist state to database."""
        sessions_storage.update_build_state(
            self.project_id,
            self.session_id,
            self._state,
        )
