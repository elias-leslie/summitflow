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


def _parse_iso_datetime(value: str | datetime | None) -> datetime | None:
    """Parse ISO datetime string, handling Z suffix. Returns None if input is None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


# Conciseness rules
MAX_TITLE_LENGTH = 100
MAX_CONTENT_LENGTH = 500
MAX_SENTENCES = 3
HEDGING_WORDS = [
    "might",
    "maybe",
    "perhaps",
    "possibly",
    "could be",
    "sometimes",
    "often",
    "usually",
    "generally",
    "typically",
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
            violations.append(f"Title exceeds {MAX_TITLE_LENGTH} chars ({len(title)} chars)")

        # Content length
        if len(content) > MAX_CONTENT_LENGTH:
            violations.append(f"Content exceeds {MAX_CONTENT_LENGTH} chars ({len(content)} chars)")

        # Sentence count
        sentences = re.split(r"[.!?]+", content.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        if len(sentences) > MAX_SENTENCES:
            violations.append(f"Content has {len(sentences)} sentences (max {MAX_SENTENCES})")

        # Hedging words
        content_lower = content.lower()
        found_hedging = [w for w in HEDGING_WORDS if w in content_lower]
        if found_hedging:
            violations.append(f"Content contains hedging words: {', '.join(found_hedging)}")

        return len(violations) == 0, violations

    # =========================================================================
    # Feedback & Ranking
    # =========================================================================

    @staticmethod
    def get_approval_boost(pattern: dict[str, Any]) -> float:
        """Calculate approval boost multiplier for pattern ranking.

        Approved patterns get a 10% boost.
        Rejected patterns get graduated penalties:
        - 1-2 rejections: 0.9x (10% penalty)
        - 3-4 rejections: 0.7x (30% penalty)
        - 5+ rejections: 0.5x (50% penalty)

        Args:
            pattern: Pattern dict with approval_count, rejection_count, status

        Returns:
            Multiplier (0.5-1.1) to apply to pattern ranking score.
        """
        status = pattern.get("status", "pending")
        approval_count = pattern.get("approval_count", 0) or 0
        rejection_count = pattern.get("rejection_count", 0) or 0

        # Base multiplier
        multiplier = 1.0

        # Approved/applied patterns get boost
        if status in ("approved", "applied") or approval_count > 0:
            multiplier = 1.1  # +10% boost

        # Rejection penalties (can override approval boost)
        if rejection_count >= 5:
            multiplier = 0.5  # 50% penalty
        elif rejection_count >= 3:
            multiplier = 0.7  # 30% penalty
        elif rejection_count >= 1:
            multiplier = 0.9  # 10% penalty

        return multiplier

    @staticmethod
    def get_source_observation_boost(
        observation: dict[str, Any],
        pattern_multiplier: float = 1.0,
    ) -> float:
        """Apply inherited boost to source observations from approved patterns.

        When a pattern is approved, observations that sourced it get a boost.

        Args:
            observation: Observation dict
            pattern_multiplier: Boost from the parent pattern

        Returns:
            Additional boost (0.0-0.1) to add to observation score.
        """
        # Inherited boost is 50% of the pattern's boost above 1.0
        if pattern_multiplier > 1.0:
            return (pattern_multiplier - 1.0) * 0.5
        return 0.0

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

        memory_storage.update_pattern_status(
            pattern_id=pattern_id,
            status=new_status,
            reviewed_by=reason,  # Use reviewed_by for the reason
        )
        return self.get_pattern(pattern_id)

    def apply_pattern(
        self,
        pattern_id: str,
        rules_file: str = "learned-patterns.md",
    ) -> dict[str, Any] | None:
        """Apply a pattern by writing to .claude/rules/.

        Handles different actions:
        - add: Append to rules file
        - update: Find and replace existing pattern
        - remove: Remove pattern from rules file
        - merge: Apply merged content and mark originals

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
            # Remove the pattern from rules file
            self._remove_pattern_from_file(rules_path, pattern["target_pattern_id"])
            logger.info(f"pattern_removed: id={pattern_id} target={pattern['target_pattern_id']}")

        elif action == "update":
            # Update existing pattern in rules file
            if pattern.get("target_pattern_id"):
                self._remove_pattern_from_file(rules_path, pattern["target_pattern_id"])
            self._append_pattern_to_file(rules_path, pattern)
            logger.info(
                f"pattern_updated: id={pattern_id} target={pattern.get('target_pattern_id')}"
            )

        elif action == "merge":
            # Remove source patterns and add merged version
            source_ids = pattern.get("source_diary_ids") or []
            for source_id in source_ids:
                self._remove_pattern_from_file(rules_path, source_id)
            self._append_pattern_to_file(rules_path, pattern)
            logger.info(f"pattern_merged: id={pattern_id} sources={source_ids}")

        else:  # add
            self._append_pattern_to_file(rules_path, pattern)
            logger.info(f"pattern_applied: id={pattern_id} file={rules_path}")

        # Update status
        memory_storage.mark_pattern_applied(pattern_id)
        return self.get_pattern(pattern_id)

    def _append_pattern_to_file(self, rules_path: Path, pattern: dict[str, Any]) -> None:
        """Append a formatted pattern to the rules file."""
        pattern_entry = self._format_pattern_for_rules(pattern)
        with open(rules_path, "a") as f:
            f.write("\n\n" + pattern_entry)

    def _remove_pattern_from_file(self, rules_path: Path, pattern_id: str | None) -> bool:
        """Remove a pattern from the rules file by its ID.

        Args:
            rules_path: Path to the rules file.
            pattern_id: The pattern ID to remove.

        Returns:
            True if pattern was found and removed.
        """
        if not pattern_id or not rules_path.exists():
            return False

        try:
            content = rules_path.read_text()

            # Find and remove the pattern section
            # Pattern sections are marked with <!-- Pattern ID: xxx -->
            pattern_marker = f"<!-- Pattern ID: {pattern_id}"

            if pattern_marker not in content:
                return False

            # Find the pattern section boundaries
            # Patterns start with "## title" and end before next "## " or end of file
            lines = content.split("\n")
            new_lines = []
            skip_until_next_section = False
            found_pattern = False

            for line in lines:
                # Check if this line contains the pattern marker we're looking for
                if pattern_marker in line:
                    # Find the start of this section (go back to the ## heading)
                    j = len(new_lines) - 1
                    while j >= 0 and not new_lines[j].startswith("## "):
                        j -= 1
                    # Remove from the heading onwards
                    if j >= 0:
                        new_lines = new_lines[:j]
                    skip_until_next_section = True
                    found_pattern = True
                    continue

                if skip_until_next_section:
                    if line.startswith("## "):
                        skip_until_next_section = False
                        new_lines.append(line)
                    continue

                new_lines.append(line)

            if found_pattern:
                # Clean up extra blank lines
                cleaned = "\n".join(new_lines).strip()
                rules_path.write_text(cleaned + "\n")
                logger.info(f"pattern_removed_from_file: id={pattern_id}")
                return True

        except Exception as e:
            logger.error(f"Failed to remove pattern from file: {e}")

        return False

    def _format_pattern_for_rules(self, pattern: dict[str, Any]) -> str:
        """Format a pattern as markdown for rules file."""
        lines = [
            f"## {pattern['title']}",
            "",
            pattern["content"],
        ]

        if pattern.get("rationale"):
            lines.extend(
                [
                    "",
                    f"*Rationale: {pattern['rationale']}*",
                ]
            )

        lines.extend(
            [
                "",
                f"<!-- Pattern ID: {pattern['id']} | Applied: {datetime.now().isoformat()} -->",
            ]
        )

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
            last_used = _parse_iso_datetime(p.get("last_used_at"))
            if last_used:
                if last_used < cutoff:
                    stale.append(p)
            else:
                # Never used - check if applied long ago
                applied_at = _parse_iso_datetime(p.get("applied_at") or p.get("created_at"))
                if applied_at and applied_at < cutoff:
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
        input_words = set(re.findall(r"\w+", (title + " " + content).lower()))

        similar = []
        for p in existing:
            # Tokenize existing pattern
            existing_words = set(re.findall(r"\w+", (p["title"] + " " + p["content"]).lower()))

            # Calculate Jaccard similarity
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
                reviewed_by=f"Merged into {merged['id']}",
            )

        logger.info(f"patterns_merged: source={pattern_ids} target={merged['id']}")

        return merged

    # =========================================================================
    # Usage Tracking
    # =========================================================================

    def record_usage(self, pattern_id: str) -> bool:
        """Record that a pattern was used.

        Updates usage_count and last_used_at.

        Args:
            pattern_id: The pattern ID.

        Returns:
            True if updated successfully.
        """
        result = memory_storage.increment_pattern_usage(pattern_id)
        return result is not None

    # =========================================================================
    # Global Pattern Promotion
    # =========================================================================

    def promote_to_global(self, pattern_id: str) -> dict[str, Any]:
        """Promote a pattern to global scope for use across all projects.

        Creates a copy of the pattern with project_id='_global_'. Global patterns
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

        # Create global copy using memory_storage directly (bypasses project_id check)
        global_pattern = memory_storage.create_pattern(
            project_id="_global_",
            pattern_type=pattern.get("pattern_type", "rule"),
            title=pattern["title"],
            content=pattern["content"],
            action="add",
            rationale=f"Promoted from {self.project_id}: {pattern.get('rationale', '')}",
            source_diary_ids=[pattern_id],  # Reference source pattern
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
