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

logger = logging.getLogger(__name__)

# Conciseness rules
MAX_TITLE_LENGTH = 100
MAX_CONTENT_LENGTH = 500
MAX_SENTENCES = 3
HEDGING_WORDS = [
    "might", "maybe", "perhaps", "possibly", "could be",
    "sometimes", "often", "usually", "generally", "typically",
]


class PatternService:
    """Service for managing patterns with full lifecycle support.

    Pattern lifecycle:
    1. pending: Newly discovered, awaiting human review
    2. approved: Reviewed and accepted, ready to apply
    3. applied: Written to .claude/rules/ file
    4. rejected: Not useful, won't be applied
    5. merged: Superseded by another pattern
    """

    def __init__(self, project_id: str, project_path: str | None = None):
        """Initialize the pattern service.

        Args:
            project_id: The project to manage patterns for.
            project_path: Path to the project root (for writing rules).
        """
        self.project_id = project_id
        self.project_path = project_path

    # =========================================================================
    # Validation
    # =========================================================================

    def validate_conciseness(
        self,
        title: str,
        content: str,
    ) -> tuple[bool, list[str]]:
        """Validate pattern content for conciseness.

        Rules:
        - Title max 100 chars
        - Content max 500 chars
        - Max 3 sentences
        - No hedging words

        Args:
            title: Pattern title.
            content: Pattern content.

        Returns:
            Tuple of (is_valid, list of violation messages).
        """
        violations = []

        # Title length
        if len(title) > MAX_TITLE_LENGTH:
            violations.append(
                f"Title exceeds {MAX_TITLE_LENGTH} chars ({len(title)} chars)"
            )

        # Content length
        if len(content) > MAX_CONTENT_LENGTH:
            violations.append(
                f"Content exceeds {MAX_CONTENT_LENGTH} chars ({len(content)} chars)"
            )

        # Sentence count
        sentences = re.split(r'[.!?]+', content.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        if len(sentences) > MAX_SENTENCES:
            violations.append(
                f"Content has {len(sentences)} sentences (max {MAX_SENTENCES})"
            )

        # Hedging words
        content_lower = content.lower()
        found_hedging = [w for w in HEDGING_WORDS if w in content_lower]
        if found_hedging:
            violations.append(
                f"Content contains hedging words: {', '.join(found_hedging)}"
            )

        return len(violations) == 0, violations

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
            status="pending",
            action=action,
            rationale=rationale,
            source_entry_ids=source_entry_ids,
            confidence=confidence,
        )

        logger.info(
            f"pattern_created: id={pattern['id']} type={pattern_type} action={action}"
        )

        return pattern

    def get_pattern(self, pattern_id: str) -> dict[str, Any] | None:
        """Get a pattern by ID.

        Args:
            pattern_id: The pattern ID.

        Returns:
            The pattern or None if not found.
        """
        return memory_storage.get_pattern(pattern_id)

    def list_patterns(
        self,
        status: str | None = None,
        pattern_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List patterns with filtering.

        Args:
            status: Filter by status.
            pattern_type: Filter by type.
            limit: Maximum patterns to return.
            offset: Offset for pagination.

        Returns:
            List of patterns.
        """
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
            "applied": [],  # Terminal state
            "rejected": ["pending"],  # Allow re-review
            "merged": [],  # Terminal state
        }

        if new_status not in valid_transitions.get(current, []):
            raise ValueError(
                f"Invalid transition: {current} -> {new_status}. "
                f"Valid: {valid_transitions.get(current, [])}"
            )

        return memory_storage.update_pattern_status(
            pattern_id=pattern_id,
            status=new_status,
            status_reason=reason,
        )

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

        # Write to .claude/rules/
        rules_dir = Path(self.project_path) / ".claude" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)

        rules_path = rules_dir / rules_file
        pattern_entry = self._format_pattern_for_rules(pattern)

        # Append to file
        with open(rules_path, "a") as f:
            f.write("\n\n" + pattern_entry)

        logger.info(
            f"pattern_applied: id={pattern_id} file={rules_path}"
        )

        # Update status
        return memory_storage.update_pattern_status(
            pattern_id=pattern_id,
            status="applied",
            applied_at=datetime.now(),
        )

    def _format_pattern_for_rules(self, pattern: dict[str, Any]) -> str:
        """Format a pattern as markdown for rules file."""
        lines = [
            f"## {pattern['title']}",
            "",
            pattern["content"],
        ]

        if pattern.get("rationale"):
            lines.extend([
                "",
                f"*Rationale: {pattern['rationale']}*",
            ])

        lines.extend([
            "",
            f"<!-- Pattern ID: {pattern['id']} | Applied: {datetime.now().isoformat()} -->",
        ])

        return "\n".join(lines)

    # =========================================================================
    # Staleness Detection
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
            last_used = p.get("last_used_at")
            if last_used:
                # Parse datetime if string
                if isinstance(last_used, str):
                    last_used = datetime.fromisoformat(last_used.replace("Z", "+00:00"))
                if last_used < cutoff:
                    stale.append(p)
            else:
                # Never used - check if applied long ago
                applied_at = p.get("applied_at") or p.get("created_at")
                if applied_at:
                    if isinstance(applied_at, str):
                        applied_at = datetime.fromisoformat(applied_at.replace("Z", "+00:00"))
                    if applied_at < cutoff:
                        stale.append(p)

        return stale

    # =========================================================================
    # Duplicate Detection
    # =========================================================================

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

        # Tokenize input
        input_words = set(re.findall(r'\w+', (title + " " + content).lower()))

        similar = []
        for p in existing:
            # Tokenize existing pattern
            existing_words = set(
                re.findall(r'\w+', (p["title"] + " " + p["content"]).lower())
            )

            # Calculate Jaccard similarity
            if not input_words or not existing_words:
                continue

            intersection = len(input_words & existing_words)
            union = len(input_words | existing_words)
            similarity = intersection / union

            if similarity >= similarity_threshold:
                similar.append({
                    **p,
                    "similarity_score": round(similarity, 2),
                })

        # Sort by similarity descending
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
        # Create new merged pattern
        merged = self.create_pattern(
            pattern_type="rule",
            title=merged_title,
            content=merged_content,
            action="merge",
            rationale=rationale,
            source_entry_ids=pattern_ids,  # Reference original patterns
        )

        # Mark originals as merged
        for pid in pattern_ids:
            memory_storage.update_pattern_status(
                pattern_id=pid,
                status="merged",
                status_reason=f"Merged into {merged['id']}",
            )

        logger.info(
            f"patterns_merged: source={pattern_ids} target={merged['id']}"
        )

        return merged

    # =========================================================================
    # Usage Tracking
    # =========================================================================

    def record_usage(self, pattern_id: str) -> dict[str, Any] | None:
        """Record that a pattern was used.

        Updates usage_count and last_used_at.

        Args:
            pattern_id: The pattern ID.

        Returns:
            Updated pattern or None if not found.
        """
        return memory_storage.increment_pattern_usage(pattern_id)
