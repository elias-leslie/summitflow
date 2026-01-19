"""Attempt history tracking for circular fix prevention.

Tracks fix attempts per task/error with semantic hashing to detect when
the same fix is being attempted repeatedly (circular fixes).

Per d9 decision: Store attempt_history.json per task containing semantic
hash of error + code state. Track {attempt_number, error_hash, diff_hash,
approach_summary, outcome, timestamp}. Before each fix attempt, check if
diff_hash already exists with 2+ failures → escalate.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)

# Default location for attempt history files (in worktree)
ATTEMPT_HISTORY_FILENAME = ".summitflow/attempt_history.json"


@dataclass
class Attempt:
    """Single fix attempt record."""

    attempt_number: int
    error_hash: str
    diff_hash: str | None
    approach_summary: str
    outcome: str  # "success", "failed", "skipped"
    timestamp: str
    model: str | None = None
    escalation_level: str | None = None  # "WORKER", "SUPERVISOR", "HUMAN"


@dataclass
class TaskAttemptHistory:
    """Attempt history for a single task/error."""

    task_id: str
    error_signature: str
    file_path: str | None
    attempts: list[Attempt]
    created_at: str
    updated_at: str


def compute_error_hash(
    check_type: str,
    error_code: str,
    error_message: str,
    file_path: str | None = None,
    line_number: int | None = None,
) -> str:
    """Compute a semantic hash for an error.

    The hash uniquely identifies an error regardless of surrounding code changes.

    Args:
        check_type: Type of check (ruff, mypy, etc.)
        error_code: Error code (F401, etc.)
        error_message: Error message (normalized)
        file_path: Path to file with error
        line_number: Line number (optional, may change)

    Returns:
        SHA256 hash string (first 16 chars)
    """
    # Normalize error message (remove line numbers, paths, etc.)
    normalized_message = _normalize_error_message(error_message)

    components = [
        check_type,
        error_code,
        normalized_message,
        file_path or "",
    ]

    content = "|".join(components)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def compute_diff_hash(original_content: str, new_content: str) -> str:
    """Compute a hash of the diff between two file contents.

    Used to detect when the same fix is being attempted multiple times.

    Args:
        original_content: Original file content
        new_content: Proposed fix content

    Returns:
        SHA256 hash string (first 16 chars)
    """
    # Create a simple diff representation
    orig_lines = set(original_content.splitlines())
    new_lines = set(new_content.splitlines())

    # Lines added and removed
    added = new_lines - orig_lines
    removed = orig_lines - new_lines

    # Sort for consistency
    diff_repr = "ADDED:" + "|".join(sorted(added)) + "REMOVED:" + "|".join(sorted(removed))

    return hashlib.sha256(diff_repr.encode()).hexdigest()[:16]


def _normalize_error_message(message: str) -> str:
    """Normalize error message for consistent hashing.

    Removes variable parts like line numbers and specific values.

    Args:
        message: Raw error message

    Returns:
        Normalized message
    """
    import re

    # Remove line/column numbers like "line 42" or "42:13"
    message = re.sub(r"line \d+", "line N", message, flags=re.IGNORECASE)
    message = re.sub(r":\d+:\d+", ":N:N", message)
    message = re.sub(r"\[\d+\]", "[N]", message)

    # Remove specific paths but keep file names
    message = re.sub(r'["\']?(/[^"\':\s]+)+["\']?', "PATH", message)

    # Normalize whitespace
    message = " ".join(message.split())

    return message.strip()


class AttemptHistory:
    """Manages attempt history for circular fix detection.

    Stores history in .summitflow/attempt_history.json within the worktree.
    Each error gets its own entry keyed by error_hash.

    Usage:
        history = AttemptHistory(worktree_path)

        # Before attempting a fix
        if history.is_circular_fix(error_hash, proposed_diff_hash):
            # Escalate - same fix already attempted 2+ times

        # After a fix attempt
        history.record_attempt(
            task_id="task-123",
            error_hash=error_hash,
            diff_hash=diff_hash,
            approach_summary="Remove unused import",
            outcome="failed",
            model="gemini-flash",
        )

        # Get previous approaches to avoid repetition
        approaches = history.get_previous_approaches(error_hash)
    """

    def __init__(self, worktree_path: Path | str):
        """Initialize attempt history for a worktree.

        Args:
            worktree_path: Path to worktree root
        """
        self.worktree_path = Path(worktree_path)
        self.history_file = self.worktree_path / ATTEMPT_HISTORY_FILENAME
        self._history: dict[str, TaskAttemptHistory] = {}
        self._load()

    def _load(self) -> None:
        """Load history from file."""
        if not self.history_file.exists():
            self._history = {}
            return

        try:
            data = json.loads(self.history_file.read_text())
            self._history = {}
            for error_hash, entry in data.items():
                attempts = [Attempt(**a) for a in entry.get("attempts", [])]
                self._history[error_hash] = TaskAttemptHistory(
                    task_id=entry["task_id"],
                    error_signature=entry["error_signature"],
                    file_path=entry.get("file_path"),
                    attempts=attempts,
                    created_at=entry["created_at"],
                    updated_at=entry["updated_at"],
                )
            logger.debug("attempt_history_loaded", count=len(self._history))
        except Exception as e:
            logger.warning("attempt_history_load_failed", error=str(e))
            self._history = {}

    def _save(self) -> None:
        """Save history to file."""
        try:
            # Ensure directory exists
            self.history_file.parent.mkdir(parents=True, exist_ok=True)

            # Convert to JSON-serializable dict
            data: dict[str, Any] = {}
            for error_hash, entry in self._history.items():
                data[error_hash] = {
                    "task_id": entry.task_id,
                    "error_signature": entry.error_signature,
                    "file_path": entry.file_path,
                    "attempts": [asdict(a) for a in entry.attempts],
                    "created_at": entry.created_at,
                    "updated_at": entry.updated_at,
                }

            self.history_file.write_text(json.dumps(data, indent=2))
            logger.debug("attempt_history_saved", count=len(self._history))
        except Exception as e:
            logger.error("attempt_history_save_failed", error=str(e))

    def record_attempt(
        self,
        task_id: str,
        error_hash: str,
        diff_hash: str | None,
        approach_summary: str,
        outcome: str,
        model: str | None = None,
        escalation_level: str | None = None,
        error_signature: str = "",
        file_path: str | None = None,
    ) -> Attempt:
        """Record a fix attempt.

        Args:
            task_id: Task ID being fixed
            error_hash: Semantic hash of the error
            diff_hash: Hash of the proposed fix (None if no fix attempted)
            approach_summary: Brief description of the approach
            outcome: Result ("success", "failed", "skipped")
            model: Model used for the fix
            escalation_level: Current escalation level
            error_signature: Original error signature for context
            file_path: Path to file being fixed

        Returns:
            The recorded Attempt
        """
        now = datetime.now(UTC).isoformat()

        # Get or create entry for this error
        if error_hash not in self._history:
            self._history[error_hash] = TaskAttemptHistory(
                task_id=task_id,
                error_signature=error_signature,
                file_path=file_path,
                attempts=[],
                created_at=now,
                updated_at=now,
            )

        entry = self._history[error_hash]
        attempt_number = len(entry.attempts) + 1

        attempt = Attempt(
            attempt_number=attempt_number,
            error_hash=error_hash,
            diff_hash=diff_hash,
            approach_summary=approach_summary,
            outcome=outcome,
            timestamp=now,
            model=model,
            escalation_level=escalation_level,
        )

        entry.attempts.append(attempt)
        entry.updated_at = now

        self._save()

        logger.info(
            "attempt_recorded",
            task_id=task_id,
            error_hash=error_hash,
            attempt_number=attempt_number,
            outcome=outcome,
        )

        return attempt

    def is_circular_fix(
        self,
        error_hash: str,
        proposed_diff_hash: str,
        threshold: int = 2,
    ) -> bool:
        """Check if a proposed fix is circular (same fix attempted before).

        A fix is circular if the same diff_hash has been attempted `threshold`
        or more times without success.

        Args:
            error_hash: Hash of the error being fixed
            proposed_diff_hash: Hash of the proposed fix
            threshold: Number of failed attempts before considering circular

        Returns:
            True if this is a circular fix that should trigger escalation
        """
        if error_hash not in self._history:
            return False

        entry = self._history[error_hash]

        # Count failed attempts with the same diff_hash
        failed_same_diff = sum(
            1 for a in entry.attempts if a.diff_hash == proposed_diff_hash and a.outcome == "failed"
        )

        is_circular = failed_same_diff >= threshold

        if is_circular:
            logger.warning(
                "circular_fix_detected",
                error_hash=error_hash,
                diff_hash=proposed_diff_hash,
                failed_count=failed_same_diff,
                threshold=threshold,
            )

        return is_circular

    def get_previous_approaches(
        self,
        error_hash: str,
        include_successful: bool = True,
    ) -> list[dict[str, Any]]:
        """Get previous fix approaches for an error.

        Useful for injecting into prompts to avoid repeating failed approaches.

        Args:
            error_hash: Hash of the error
            include_successful: Whether to include successful attempts

        Returns:
            List of approach summaries with outcomes
        """
        if error_hash not in self._history:
            return []

        entry = self._history[error_hash]
        approaches = []

        for attempt in entry.attempts:
            if not include_successful and attempt.outcome == "success":
                continue

            approaches.append(
                {
                    "attempt_number": attempt.attempt_number,
                    "approach_summary": attempt.approach_summary,
                    "outcome": attempt.outcome,
                    "model": attempt.model,
                    "escalation_level": attempt.escalation_level,
                    "diff_hash": attempt.diff_hash,
                }
            )

        return approaches

    def get_failed_diff_hashes(self, error_hash: str) -> set[str]:
        """Get set of diff hashes that have failed for an error.

        Args:
            error_hash: Hash of the error

        Returns:
            Set of diff hashes that failed
        """
        if error_hash not in self._history:
            return set()

        entry = self._history[error_hash]
        return {
            a.diff_hash for a in entry.attempts if a.outcome == "failed" and a.diff_hash is not None
        }

    def get_attempt_count(self, error_hash: str) -> int:
        """Get total attempt count for an error.

        Args:
            error_hash: Hash of the error

        Returns:
            Number of attempts
        """
        if error_hash not in self._history:
            return 0

        return len(self._history[error_hash].attempts)

    def clear(self, error_hash: str | None = None) -> None:
        """Clear attempt history.

        Args:
            error_hash: If provided, clear only this error. Otherwise clear all.
        """
        if error_hash:
            if error_hash in self._history:
                del self._history[error_hash]
        else:
            self._history = {}

        self._save()
        logger.info("attempt_history_cleared", error_hash=error_hash)
