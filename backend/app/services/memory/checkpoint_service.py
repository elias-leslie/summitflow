"""Checkpoint Service - Pause and resume agent sessions.

Enables seamless pause/resume across sessions by:
1. Saving agent state (current action, completed/remaining steps)
2. Generating resume prompts that restore context
3. Tracking conversation summary and decisions made
"""

from __future__ import annotations

import logging
from typing import Any

from app.storage import memory as memory_storage

logger = logging.getLogger(__name__)


class CheckpointService:
    """Service for creating and managing agent checkpoints.

    Checkpoints capture the state of an agent session so work can be
    resumed later without losing context.
    """

    def __init__(self, project_id: str):
        """Initialize the checkpoint service.

        Args:
            project_id: The project to manage checkpoints for.
        """
        self.project_id = project_id

    def create_checkpoint(
        self,
        session_id: str,
        agent_type: str,
        current_action: str | None = None,
        question: str | None = None,
        options: list[dict[str, Any]] | None = None,
        recommendation: str | None = None,
        completed_steps: list[str] | None = None,
        remaining_steps: list[str] | None = None,
        files_modified: list[str] | None = None,
        decisions_made: list[dict[str, Any]] | None = None,
        conversation_summary: str | None = None,
        context_snapshot: dict[str, Any] | None = None,
        tokens_used: int | None = None,
    ) -> dict[str, Any] | None:
        """Create a checkpoint to save current agent state.

        Args:
            session_id: The session ID for this checkpoint.
            agent_type: Type of agent (claude, gemini, claude-code).
            current_action: What the agent was doing when paused.
            question: Any pending question for the user.
            options: Options presented with the question.
            recommendation: Agent's recommendation if applicable.
            completed_steps: List of steps completed so far.
            remaining_steps: List of steps still to do.
            files_modified: Files that were modified in the session.
            decisions_made: Key decisions made during the session.
            conversation_summary: Summary of the conversation so far.
            context_snapshot: Additional context to preserve.
            tokens_used: Tokens used in the session so far.

        Returns:
            The created checkpoint, or None if memory is disabled.
        """
        checkpoint = memory_storage.create_checkpoint(
            project_id=self.project_id,
            session_id=session_id,
            agent_type=agent_type,
            current_action=current_action,
            question=question,
            options=options,
            recommendation=recommendation,
            completed_steps=completed_steps,
            remaining_steps=remaining_steps,
            files_modified=files_modified,
            decisions_made=decisions_made,
            conversation_summary=conversation_summary,
            context_snapshot=context_snapshot,
            tokens_used=tokens_used,
        )

        if checkpoint is None:
            logger.debug(f"checkpoint_skipped: memory disabled for {self.project_id}")
            return None

        logger.info(
            f"checkpoint_created: id={checkpoint['id']} session={session_id} agent={agent_type}"
        )

        return checkpoint

    def get_checkpoint(self, session_id: str) -> dict[str, Any] | None:
        """Get the latest checkpoint for a session.

        Args:
            session_id: The session ID to get checkpoint for.

        Returns:
            The checkpoint or None if not found.
        """
        return memory_storage.get_latest_checkpoint(session_id)

    def get_checkpoint_by_id(self, checkpoint_id: str) -> dict[str, Any] | None:
        """Get a checkpoint by its ID.

        Args:
            checkpoint_id: The checkpoint ID.

        Returns:
            The checkpoint or None if not found.
        """
        checkpoints = memory_storage.list_checkpoints(
            project_id=self.project_id,
            limit=100,
        )
        return next((c for c in checkpoints if c["id"] == checkpoint_id), None)

    def list_checkpoints(
        self,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List checkpoints for the project.

        Args:
            limit: Maximum checkpoints to return.
            offset: Offset for pagination.

        Returns:
            List of checkpoints.
        """
        return memory_storage.list_checkpoints(
            project_id=self.project_id,
            limit=limit,
            offset=offset,
        )

    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint.

        Args:
            checkpoint_id: The checkpoint ID to delete.

        Returns:
            True if deleted, False if not found.
        """
        return memory_storage.delete_checkpoint(checkpoint_id)

    def generate_resume_prompt(
        self,
        checkpoint: dict[str, Any],
        include_context: bool = True,
    ) -> str:
        """Generate a resume prompt from a checkpoint.

        Creates a prompt that can be given to an agent to resume work
        from where it left off.

        Args:
            checkpoint: The checkpoint to resume from.
            include_context: Whether to include context snapshot.

        Returns:
            A prompt string for resuming the session.
        """
        lines = [
            "# Resume Session",
            "",
            f"**Session ID:** {checkpoint['session_id']}",
            f"**Agent:** {checkpoint['agent_type']}",
            f"**Created:** {checkpoint['created_at']}",
            "",
        ]

        # Conversation summary
        if checkpoint.get("conversation_summary"):
            lines.extend(
                [
                    "## Previous Context",
                    checkpoint["conversation_summary"],
                    "",
                ]
            )

        # What was being done
        if checkpoint.get("current_action"):
            lines.extend(
                [
                    "## Current Work",
                    f"You were working on: {checkpoint['current_action']}",
                    "",
                ]
            )

        # Pending question
        if checkpoint.get("question"):
            lines.extend(
                [
                    "## Pending Question",
                    checkpoint["question"],
                    "",
                ]
            )
            if checkpoint.get("options"):
                lines.append("Options:")
                for opt in checkpoint["options"]:
                    label = opt.get("label", str(opt))
                    lines.append(f"  - {label}")
                lines.append("")
            if checkpoint.get("recommendation"):
                lines.append(f"Recommendation: {checkpoint['recommendation']}")
                lines.append("")

        # Progress
        completed = checkpoint.get("completed_steps") or []
        remaining = checkpoint.get("remaining_steps") or []

        if completed or remaining:
            lines.append("## Progress")
            if completed:
                lines.append(f"Completed ({len(completed)}):")
                for step in completed[:10]:  # Limit to 10
                    lines.append(f"  ✓ {step}")
                if len(completed) > 10:
                    lines.append(f"  ... and {len(completed) - 10} more")
            if remaining:
                lines.append(f"Remaining ({len(remaining)}):")
                for step in remaining[:10]:
                    lines.append(f"  ○ {step}")
                if len(remaining) > 10:
                    lines.append(f"  ... and {len(remaining) - 10} more")
            lines.append("")

        # Files modified
        if checkpoint.get("files_modified"):
            lines.append("## Files Modified")
            for f in checkpoint["files_modified"][:10]:
                lines.append(f"  - {f}")
            lines.append("")

        # Decisions made
        if checkpoint.get("decisions_made"):
            lines.append("## Key Decisions")
            for dec in checkpoint["decisions_made"][:5]:
                if isinstance(dec, dict):
                    what = dec.get("decision", str(dec))
                    why = dec.get("rationale", "")
                    lines.append(f"  - {what}")
                    if why:
                        lines.append(f"    Rationale: {why}")
                else:
                    lines.append(f"  - {dec}")
            lines.append("")

        # Context snapshot (optional)
        if include_context and checkpoint.get("context_snapshot"):
            lines.append("## Additional Context")
            ctx = checkpoint["context_snapshot"]
            if isinstance(ctx, dict):
                for key, value in list(ctx.items())[:5]:
                    lines.append(f"  - {key}: {str(value)[:100]}")
            lines.append("")

        # Resume instruction
        lines.extend(
            [
                "---",
                "",
                "**Please continue from where you left off.**",
                "Review the context above and resume working on the remaining tasks.",
            ]
        )

        return "\n".join(lines)

    def create_from_session_end(
        self,
        session_id: str,
        agent_type: str,
        summary: str,
        completed: list[str] | None = None,
        remaining: list[str] | None = None,
        files: list[str] | None = None,
        tokens: int | None = None,
    ) -> dict[str, Any]:
        """Convenience method to create checkpoint at session end.

        Args:
            session_id: The session ID.
            agent_type: Type of agent.
            summary: Summary of what was accomplished.
            completed: Steps completed.
            remaining: Steps remaining.
            files: Files modified.
            tokens: Tokens used.

        Returns:
            The created checkpoint.
        """
        checkpoint = self.create_checkpoint(
            session_id=session_id,
            agent_type=agent_type,
            current_action="Session ended",
            conversation_summary=summary,
            completed_steps=completed,
            remaining_steps=remaining,
            files_modified=files,
            tokens_used=tokens,
        )
        if not checkpoint:
            raise ValueError("Failed to create checkpoint")
        return checkpoint
