"""Diary Service - Session-level summaries for pattern learning.

Diary entries capture what happened in a session/task so the reflection
system can analyze patterns across multiple sessions.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.storage import memory as memory_storage

logger = logging.getLogger(__name__)


class DiaryService:
    """Service for managing diary entries.

    Diary entries are session-level summaries that capture:
    - What was attempted
    - What succeeded/failed
    - Key decisions made
    - Observations linked to this session

    The reflection system periodically analyzes diary entries
    to discover patterns.
    """

    def __init__(self, project_id: str):
        """Initialize the diary service.

        Args:
            project_id: The project to manage diary entries for.
        """
        self.project_id = project_id

    def create_entry(
        self,
        session_id: str,
        agent_type: str,
        outcome: str = "neutral",
        task_id: str | None = None,
        duration_seconds: int | None = None,
        tokens_used: int | None = None,
        discovery_tokens: int | None = None,
        observation_type: str | None = None,
        concepts: list[str] | None = None,
        what_worked: list[str] | None = None,
        what_failed: list[str] | None = None,
        user_corrections: list[str] | None = None,
        patterns_used: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a diary entry for a session or task.

        Args:
            session_id: The session this entry is for.
            agent_type: Which agent was used (claude, gemini, etc).
            outcome: Outcome status (success, failure, partial, neutral).
            task_id: Related task ID if applicable.
            duration_seconds: Duration of the session/task.
            tokens_used: Total tokens used.
            discovery_tokens: Tokens used for discovery/exploration.
            observation_type: Type of observations made.
            concepts: Key concepts discovered.
            what_worked: List of things that worked well.
            what_failed: List of things that failed.
            user_corrections: Corrections the user made.
            patterns_used: Patterns that were applied.

        Returns:
            The created diary entry.
        """
        entry = memory_storage.create_diary_entry(
            project_id=self.project_id,
            session_id=session_id,
            agent_type=agent_type,
            outcome=outcome,
            task_id=task_id,
            duration_seconds=duration_seconds,
            tokens_used=tokens_used,
            discovery_tokens=discovery_tokens,
            observation_type=observation_type,
            concepts=concepts,
            what_worked=what_worked,
            what_failed=what_failed,
            user_corrections=user_corrections,
            patterns_used=patterns_used,
        )

        logger.info(
            f"diary_entry_created: id={entry['id']} outcome={outcome}"
        )

        return entry

    def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        """Get a diary entry by ID.

        Args:
            entry_id: The entry ID.

        Returns:
            The diary entry or None if not found.
        """
        return memory_storage.get_diary_entry(entry_id)

    def get_entries(
        self,
        limit: int = 50,
        offset: int = 0,
        outcome: str | None = None,
        unreflected_only: bool = False,
    ) -> list[dict[str, Any]]:
        """List diary entries with filtering.

        Args:
            limit: Maximum entries to return.
            offset: Offset for pagination.
            outcome: Filter by outcome.
            unreflected_only: Only entries not yet reflected upon.

        Returns:
            List of diary entries.
        """
        return memory_storage.list_diary_entries(
            project_id=self.project_id,
            limit=limit,
            offset=offset,
            outcome=outcome,
            unreflected_only=unreflected_only,
        )

    def get_unprocessed_count(self) -> int:
        """Get count of diary entries not yet processed by reflection.

        Returns:
            Number of unprocessed entries.
        """
        return memory_storage.get_unreflected_diary_count(self.project_id)

    def mark_reflected(
        self,
        entry_ids: list[str],
        reflection_notes: str | None = None,
        patterns_generated: list[str] | None = None,
    ) -> int:
        """Mark diary entries as reflected upon.

        Args:
            entry_ids: List of entry IDs to mark.
            reflection_notes: Notes from the reflection.
            patterns_generated: IDs of patterns generated from reflection.

        Returns:
            Number of entries updated.
        """
        return memory_storage.mark_diary_entries_reflected(
            entry_ids=entry_ids,
            reflection_notes=reflection_notes,
            patterns_generated=patterns_generated,
        )

    def create_from_session_end(
        self,
        session_id: str,
        agent_type: str,
        outcome: str = "neutral",
        what_worked: list[str] | None = None,
        what_failed: list[str] | None = None,
        concepts: list[str] | None = None,
        tokens: int | None = None,
        duration: int | None = None,
    ) -> dict[str, Any]:
        """Convenience method to create diary entry at session end.

        Args:
            session_id: The session ID.
            agent_type: Type of agent used.
            outcome: Outcome status.
            what_worked: Things that worked well.
            what_failed: Things that failed.
            concepts: Key concepts.
            tokens: Tokens used.
            duration: Duration in seconds.

        Returns:
            The created diary entry.
        """
        return self.create_entry(
            session_id=session_id,
            agent_type=agent_type,
            outcome=outcome,
            what_worked=what_worked,
            what_failed=what_failed,
            concepts=concepts,
            tokens_used=tokens,
            duration_seconds=duration,
        )
