"""Pattern memory service for fix pattern storage and retrieval.

This service provides business logic for storing successful fix patterns
and retrieving similar patterns to inform future fix attempts.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

from .memory_client import FixPattern, MemoryClient, SearchResult

logger = logging.getLogger(__name__)


@dataclass
class StoredPattern:
    """A fix pattern retrieved from memory."""

    error_signature: str
    error_type: str
    file_path: str | None
    fix_diff: str
    root_cause_summary: str
    success_count: int
    similarity_score: float


def compute_error_signature(
    check_type: str,
    error_code: str,
    error_message: str,
) -> str:
    """Compute a stable signature for an error.

    The signature is used to identify similar errors across different
    files and contexts.

    Args:
        check_type: Type of check (ruff, types, pytest, etc.)
        error_code: Specific error code (F401, E0602, etc.)
        error_message: Error message (normalized)

    Returns:
        Hex digest of the error signature
    """
    # Normalize message: lowercase, strip whitespace, remove file paths
    normalized_msg = error_message.lower().strip()
    # Remove line numbers and file paths from message for stability
    parts = [check_type, error_code, normalized_msg[:100]]
    content = "|".join(parts)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


class PatternMemoryService:
    """Service for storing and retrieving fix patterns from Agent Hub memory.

    Patterns are stored with project scope to allow learning from
    project-specific fixes while avoiding cross-project contamination.
    """

    def __init__(
        self,
        project_id: str,
        client: MemoryClient | None = None,
    ):
        """Initialize the pattern memory service.

        Args:
            project_id: Project ID for scoping patterns
            client: MemoryClient instance (created if not provided)
        """
        self.client = client or MemoryClient()
        self.project_id = project_id

    async def store_fix_pattern(
        self,
        check_type: str,
        error_code: str,
        error_message: str,
        file_path: str | None,
        fix_diff: str,
        root_cause_summary: str,
    ) -> dict[str, Any]:
        """Store a successful fix pattern in Agent Hub memory.

        Called when a fix agent successfully resolves an error and the
        quality gate passes. Patterns are stored for future retrieval.

        Args:
            check_type: Type of check (ruff, types, pytest)
            error_code: Specific error code (F401, E0602)
            error_message: Full error message
            file_path: File where error occurred
            fix_diff: Git diff of the fix
            root_cause_summary: Human-readable explanation

        Returns:
            API response with episode_uuid
        """
        error_signature = compute_error_signature(check_type, error_code, error_message)

        # Create pattern with full context
        pattern = FixPattern(
            error_signature=f"{check_type}:{error_code}:{error_signature}",
            fix_diff=fix_diff,
            root_cause_summary=root_cause_summary,
            project_id=self.project_id,
            check_type=check_type,
        )

        result = await self.client.store_pattern(pattern, scope="project")
        logger.info(
            "Stored fix pattern for %s:%s (signature: %s)",
            check_type, error_code, error_signature[:8],
        )
        return result

    async def get_similar_patterns(
        self,
        check_type: str,
        error_code: str,
        error_message: str,
        min_similarity: float = 0.3,
        limit: int = 3,
    ) -> list[StoredPattern]:
        """Retrieve similar fix patterns from memory.

        Used before attempting a fix to inject relevant context
        from previous successful fixes.

        Args:
            check_type: Type of check
            error_code: Error code
            error_message: Error message
            min_similarity: Minimum similarity score (0-1)
            limit: Maximum patterns to return

        Returns:
            List of similar patterns sorted by relevance
        """
        # Build search query combining check type and error info
        query = f"{check_type} {error_code} {error_message[:100]}"

        results = await self.client.search_patterns(
            query=query,
            limit=limit,
            min_score=min_similarity,
            scope="project",
            scope_id=self.project_id,
        )

        # Convert to StoredPattern with extracted metadata
        patterns = []
        for result in results:
            pattern = self._parse_search_result(result)
            if pattern:
                patterns.append(pattern)

        logger.debug("Found %d similar patterns for %s:%s", len(patterns), check_type, error_code)
        return patterns

    def _parse_search_result(self, result: SearchResult) -> StoredPattern | None:
        """Parse a search result into a StoredPattern.

        Args:
            result: Search result from Agent Hub memory

        Returns:
            StoredPattern or None if parsing fails
        """
        try:
            # Extract error signature from pattern field
            # Format: "Fix for {error_signature}: {root_cause}"
            pattern_text = result.pattern
            applies_to = result.applies_to

            # Parse error type from applies_to (format: "check_type:ruff")
            error_type = "unknown"
            if applies_to and ":" in applies_to:
                error_type = applies_to.split(":", 1)[1]

            # Extract signature from pattern text
            error_signature = "unknown"
            if "Fix for " in pattern_text:
                sig_part = pattern_text.split("Fix for ", 1)[1]
                if ":" in sig_part:
                    error_signature = sig_part.split(":")[0]

            return StoredPattern(
                error_signature=error_signature,
                error_type=error_type,
                file_path=None,  # Not stored in current schema
                fix_diff=result.example or "",
                root_cause_summary=pattern_text,
                success_count=1,  # Not tracked in current schema
                similarity_score=result.score,
            )
        except Exception as e:
            logger.warning("Failed to parse search result: %s", e)
            return None

    async def record_gotcha(
        self,
        check_type: str,
        gotcha: str,
        context: str,
        solution: str | None = None,
    ) -> dict[str, Any]:
        """Record a gotcha/pitfall discovered during fixing.

        Used to capture edge cases and common mistakes that aren't
        full fix patterns but are useful for troubleshooting.

        Args:
            check_type: Type of check where gotcha was found
            gotcha: Description of the pitfall
            context: When/where this gotcha applies
            solution: Workaround if known

        Returns:
            API response with episode_uuid
        """
        full_context = f"{check_type}: {context}"
        return await self.client.record_gotcha(
            gotcha=gotcha,
            context=full_context,
            solution=solution,
            scope="project",
            scope_id=self.project_id,
        )
