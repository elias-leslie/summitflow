"""Pattern Service - Pattern lifecycle management.

Patterns are learnings from repeated observations that should be
applied to future work. This service manages the full lifecycle:
- Creation with validation
- Status transitions (pending -> approved -> applied)
- Application to .claude/rules/
- Staleness detection
- Duplicate detection and merging
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.storage import memory as memory_storage

from . import pattern_file_handler, pattern_scoring, pattern_validation

logger = logging.getLogger(__name__)


class PatternService:
    """Service for managing patterns with full lifecycle support.

    Pattern lifecycle:
    1. pending: Newly discovered, awaiting human review
    2. approved: Reviewed and accepted, ready to apply
    3. applied: Written to .claude/rules/ file
    4. rejected: Not useful, won't be applied
    5. merged: Superseded by another pattern
    """

    def __init__(self, project_id: str | None, project_path: str | None = None):
        """Initialize the pattern service.

        Args:
            project_id: The project to manage patterns for (None for global).
            project_path: Path to the project root (for writing rules).
        """
        self.project_id = project_id
        self.project_path = project_path

    # =========================================================================
    # Validation (delegates to pattern_validation)
    # =========================================================================

    def validate_conciseness(
        self,
        title: str,
        content: str,
    ) -> tuple[bool, list[str]]:
        """Validate pattern content for conciseness."""
        return pattern_validation.validate_conciseness(title, content)

    # =========================================================================
    # Feedback & Ranking (static methods delegate to pattern_scoring)
    # =========================================================================

    @staticmethod
    def get_approval_boost(pattern: dict[str, Any]) -> float:
        """Calculate approval boost multiplier for pattern ranking."""
        return pattern_scoring.get_approval_boost(pattern)

    @staticmethod
    def get_source_observation_boost(
        observation: dict[str, Any],
        pattern_multiplier: float = 1.0,
    ) -> float:
        """Apply inherited boost to source observations from approved patterns."""
        return pattern_scoring.get_source_observation_boost(observation, pattern_multiplier)

    @staticmethod
    def calculate_pattern_relevance(pattern: dict[str, Any]) -> float:
        """Calculate relevance score for a pattern based on age and usage."""
        return pattern_scoring.calculate_pattern_relevance(pattern)

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    def create_pattern(
        self,
        pattern_type: str,
        title: str,
        content: str,
        action: str = "add",
        rationale: str | None = None,
        source_entry_ids: list[str] | None = None,
        confidence: float = 0.5,
        validate: bool = True,
        reflected_by: str | None = None,
    ) -> dict[str, Any]:
        """Create a new pattern.

        Args:
            pattern_type: Type of pattern (rule, preference, anti-pattern).
            title: Brief, descriptive title.
            content: The pattern content (what to do/avoid).
            action: Action type (add, update, remove, merge).
            rationale: Why this pattern was discovered.
            source_entry_ids: Diary entry IDs that led to this pattern.
            confidence: Confidence score 0-1.
            validate: Whether to validate conciseness.
            reflected_by: Model that generated this pattern.

        Returns:
            The created pattern.

        Raises:
            ValueError: If validation fails and validate=True.
        """
        if validate:
            is_valid, violations = self.validate_conciseness(title, content)
            if not is_valid:
                raise ValueError(f"Pattern fails conciseness validation: {violations}")

        pattern = memory_storage.create_pattern(
            project_id=self.project_id,
            pattern_type=pattern_type,
            title=title,
            content=content,
            action=action,
            rationale=rationale,
            source_diary_ids=source_entry_ids,
            confidence=confidence,
            reflected_by=reflected_by,
        )

        if not pattern:
            raise ValueError("Failed to create pattern")

        logger.info(f"pattern_created: id={pattern['id']} type={pattern_type} action={action}")

        return pattern

    def get_pattern(self, pattern_id: str) -> dict[str, Any] | None:
        """Get a pattern by ID."""
        return memory_storage.get_pattern(pattern_id)

    def list_patterns(
        self,
        status: str | None = None,
        pattern_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List patterns with filtering."""
        return memory_storage.list_patterns(
            project_id=self.project_id,
            status=status,
            pattern_type=pattern_type,
            limit=limit,
            offset=offset,
        )

    # =========================================================================
    # Lifecycle Management
    # =========================================================================

    def update_status(
        self,
        pattern_id: str,
        new_status: str,
        reason: str | None = None,
    ) -> dict[str, Any] | None:
        """Update pattern status.

        Valid transitions:
        - pending -> approved, rejected
        - approved -> applied, rejected
        - applied -> (no transitions)
        - rejected -> pending (re-review)

        Args:
            pattern_id: The pattern ID.
            new_status: New status value.
            reason: Reason for the status change.

        Returns:
            Updated pattern or None if not found.

        Raises:
            ValueError: If transition is invalid.
        """
        pattern = self.get_pattern(pattern_id)
        if not pattern:
            return None

        current = pattern["status"]
        valid_transitions = {
            "pending": ["approved", "rejected"],
            "approved": ["applied", "rejected"],
            "applied": [],
            "rejected": ["pending"],
            "merged": [],
        }

        if new_status not in valid_transitions.get(current, []):
            raise ValueError(
                f"Invalid transition: {current} -> {new_status}. "
                f"Valid: {valid_transitions.get(current, [])}"
            )

        memory_storage.update_pattern_status(
            pattern_id=pattern_id,
            status=new_status,
            reviewed_by=reason,
        )
        return self.get_pattern(pattern_id)

    def apply_pattern(
        self,
        pattern_id: str,
        rules_file: str = "learned-patterns.md",
    ) -> dict[str, Any] | None:
        """Apply a pattern by writing to .claude/rules/.

        Args:
            pattern_id: The pattern ID.
            rules_file: Name of the rules file to write to.

        Returns:
            Updated pattern or None if not found.

        Raises:
            ValueError: If pattern is not approved.
        """
        pattern = self.get_pattern(pattern_id)
        if not pattern:
            return None

        if pattern["status"] != "approved":
            raise ValueError(
                f"Pattern must be approved before applying. Current: {pattern['status']}"
            )

        if not self.project_path:
            raise ValueError("project_path not set - cannot write rules")

        rules_dir = Path(self.project_path) / ".claude" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        rules_path = rules_dir / rules_file

        action = pattern.get("action", "add")

        if action == "remove":
            pattern_file_handler.remove_pattern_from_file(rules_path, pattern["target_pattern_id"])
            logger.info(f"pattern_removed: id={pattern_id} target={pattern['target_pattern_id']}")

        elif action == "update":
            if pattern.get("target_pattern_id"):
                pattern_file_handler.remove_pattern_from_file(
                    rules_path, pattern["target_pattern_id"]
                )
            pattern_file_handler.append_pattern_to_file(rules_path, pattern)
            logger.info(
                f"pattern_updated: id={pattern_id} target={pattern.get('target_pattern_id')}"
            )

        elif action == "merge":
            source_ids = pattern.get("source_diary_ids") or []
            for source_id in source_ids:
                pattern_file_handler.remove_pattern_from_file(rules_path, source_id)
            pattern_file_handler.append_pattern_to_file(rules_path, pattern)
            logger.info(f"pattern_merged: id={pattern_id} sources={source_ids}")

        else:
            pattern_file_handler.append_pattern_to_file(rules_path, pattern)
            logger.info(f"pattern_applied: id={pattern_id} file={rules_path}")

        memory_storage.mark_pattern_applied(pattern_id)
        return self.get_pattern(pattern_id)

    # =========================================================================
    # File parsing (static methods delegate to pattern_file_handler)
    # =========================================================================

    @staticmethod
    def format_pattern_jsonl(pattern: dict[str, Any], include_content: bool = False) -> str:
        """Format a pattern as compact JSON-lines."""
        return pattern_file_handler.format_pattern_jsonl(pattern, include_content)

    @staticmethod
    def parse_pattern_jsonl(line: str) -> dict[str, Any] | None:
        """Parse a JSON-lines pattern entry back to dict format."""
        return pattern_file_handler.parse_pattern_jsonl(line)

    @staticmethod
    def parse_patterns_file(content: str) -> list[dict[str, Any]]:
        """Parse a patterns file, detecting format automatically."""
        return pattern_file_handler.parse_patterns_file(content)

    # =========================================================================
    # Staleness and Duplicate Detection
    # =========================================================================

    def get_stale_patterns(
        self,
        days_threshold: int = 30,
    ) -> list[dict[str, Any]]:
        """Get patterns that haven't been used recently.

        Args:
            days_threshold: Days without usage to consider stale.

        Returns:
            List of stale patterns.
        """
        cutoff = datetime.now() - timedelta(days=days_threshold)

        patterns = memory_storage.list_patterns(
            project_id=self.project_id,
            status="applied",
            limit=1000,
        )

        stale = []
        for p in patterns:
            last_used = pattern_scoring.parse_iso_datetime(p.get("last_used_at"))
            if last_used:
                if last_used < cutoff:
                    stale.append(p)
            else:
                applied_at = pattern_scoring.parse_iso_datetime(
                    p.get("applied_at") or p.get("created_at")
                )
                if applied_at and applied_at < cutoff:
                    stale.append(p)

        return stale

    def detect_duplicates(
        self,
        title: str,
        content: str,
        similarity_threshold: float = 0.7,
    ) -> list[dict[str, Any]]:
        """Find patterns similar to the given content.

        Uses simple word overlap for similarity.

        Args:
            title: Title to compare.
            content: Content to compare.
            similarity_threshold: Minimum similarity score (0-1).

        Returns:
            List of similar patterns with similarity scores.
        """
        existing = memory_storage.list_patterns(
            project_id=self.project_id,
            limit=1000,
        )

        input_words = set(re.findall(r"\w+", (title + " " + content).lower()))

        similar = []
        for p in existing:
            existing_words = set(re.findall(r"\w+", (p["title"] + " " + p["content"]).lower()))

            if not input_words or not existing_words:
                continue

            intersection = len(input_words & existing_words)
            union = len(input_words | existing_words)
            similarity = intersection / union

            if similarity >= similarity_threshold:
                similar.append(
                    {
                        **p,
                        "similarity_score": round(similarity, 2),
                    }
                )

        similar.sort(key=lambda x: x["similarity_score"], reverse=True)
        return similar

    def merge_patterns(
        self,
        pattern_ids: list[str],
        merged_title: str,
        merged_content: str,
        rationale: str | None = None,
    ) -> dict[str, Any]:
        """Merge multiple patterns into one.

        Creates a new pattern and marks originals as merged.

        Args:
            pattern_ids: IDs of patterns to merge.
            merged_title: Title for merged pattern.
            merged_content: Content for merged pattern.
            rationale: Why these patterns were merged.

        Returns:
            The new merged pattern.
        """
        merged = self.create_pattern(
            pattern_type="rule",
            title=merged_title,
            content=merged_content,
            action="merge",
            rationale=rationale,
            source_entry_ids=pattern_ids,
        )

        for pid in pattern_ids:
            memory_storage.update_pattern_status(
                pattern_id=pid,
                status="merged",
                reviewed_by=f"Merged into {merged['id']}",
            )

        logger.info(f"patterns_merged: source={pattern_ids} target={merged['id']}")

        return merged

    # =========================================================================
    # Usage Tracking
    # =========================================================================

    def record_usage(self, pattern_id: str) -> bool:
        """Record that a pattern was used."""
        result = memory_storage.increment_pattern_usage(pattern_id)
        return result is not None

    # =========================================================================
    # Global Pattern Promotion
    # =========================================================================

    def promote_to_global(self, pattern_id: str) -> dict[str, Any]:
        """Promote a pattern to global scope for use across all projects.

        Creates a copy of the pattern with project_id=NULL. Global patterns
        are written to ~/.claude/rules/learned-patterns.md and apply to all projects.

        Args:
            pattern_id: The pattern ID to promote.

        Returns:
            The newly created global pattern.

        Raises:
            ValueError: If pattern not found or confidence < 0.9.
        """
        pattern = self.get_pattern(pattern_id)
        if not pattern:
            raise ValueError(f"Pattern {pattern_id} not found")

        confidence = pattern.get("confidence", 0)
        if confidence < 0.9:
            raise ValueError(
                f"Pattern confidence ({confidence:.2f}) must be >= 0.9 for global promotion"
            )

        global_pattern = memory_storage.create_pattern(
            project_id=None,
            pattern_type=pattern.get("pattern_type", "rule"),
            title=pattern["title"],
            content=pattern["content"],
            action="add",
            rationale=f"Promoted from {self.project_id}: {pattern.get('rationale', '')}",
            source_diary_ids=[pattern_id],
            confidence=confidence,
            reflected_by=pattern.get("reflected_by"),
        )

        if not global_pattern:
            raise ValueError("Failed to create global pattern")

        logger.info(
            f"pattern_promoted_to_global: "
            f"source={pattern_id} global={global_pattern['id']} project={self.project_id}"
        )

        return global_pattern
