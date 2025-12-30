"""ReflectionService - Analyze diary entries to discover patterns.

Uses LLM to analyze recent diary entries and generate pattern suggestions
with action types (add, update, remove, merge).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..agents import DualProviderClient

from app.storage.memory import get_observations_by_session

from .diary_service import DiaryService
from .pattern_service import PatternService

logger = logging.getLogger(__name__)

# Reflection prompt template
REFLECTION_PROMPT = """Analyze these recent session diary entries and extract patterns that should be learned.

## Diary Entries

{diary_entries}

---

## Existing Patterns (for detecting duplicates/updates)

{existing_patterns}

---

## Instructions

Based on the diary entries, identify patterns that the system should learn. For EACH pattern, specify:

1. **action** - One of:
   - `add` - New pattern to add
   - `update` - Existing pattern should be modified (reference target_pattern_id)
   - `remove` - Existing pattern is no longer valid (reference target_pattern_id)
   - `merge` - Multiple patterns should be consolidated (reference merge_pattern_ids)

2. **pattern_type** - One of:
   - `rule` - A rule to follow (do X, avoid Y)
   - `preference` - User/project preference
   - `anti-pattern` - Something to avoid

3. **title** - Brief, descriptive title (max 100 chars)

4. **content** - The pattern content (max 500 chars, max 3 sentences, NO hedging words like "might", "maybe", "sometimes")

5. **rationale** - Why this pattern was identified

6. **confidence** - 0.0 to 1.0 score based on:
   - How many times the pattern was observed
   - Whether it led to success or failure
   - How consistent the evidence is

7. **source_diary_ids** - List of diary entry IDs that support this pattern

8. **target_pattern_id** (for update/remove) - The existing pattern ID to modify

9. **merge_pattern_ids** (for merge) - List of pattern IDs to consolidate

## Response Format

Return a JSON array of pattern suggestions:

```json
[
  {{
    "action": "add",
    "pattern_type": "rule",
    "title": "Use dependency injection for services",
    "content": "All services should receive dependencies via constructor. Never instantiate dependencies inside methods.",
    "rationale": "Observed in 3 successful sessions - improves testability",
    "confidence": 0.85,
    "source_diary_ids": ["uuid1", "uuid2", "uuid3"]
  }},
  {{
    "action": "update",
    "pattern_type": "rule",
    "title": "Error handling in API routes",
    "content": "Use HTTPException for all expected errors. Let unexpected errors propagate.",
    "rationale": "Previous pattern was too vague - adding specifics from recent work",
    "confidence": 0.75,
    "source_diary_ids": ["uuid4"],
    "target_pattern_id": "existing-pattern-uuid"
  }}
]
```

## Pattern Quality Rules

**CRITICAL: Patterns must be copy-paste actionable.**

For **command/shell errors**, include:
- The exact command that works (e.g., `psql -d summitflow -c "SELECT 1"`)
- The import statement or function call (e.g., `from app.storage.connection import get_connection`)

For **code errors**, include:
- The exact import path (e.g., `from app.utils.helpers import format_date`)
- The function signature or class name

For **configuration errors**, include:
- The exact setting name and value
- The file path where it should be set

**BAD patterns (too abstract):**
- "Prioritize database role configuration in environments" (HOW?)
- "Ensure proper error handling" (WHAT specific handling?)
- "Use correct imports" (WHICH imports?)

**GOOD patterns (actionable):**
- "Use `from app.storage.connection import get_connection` instead of `psycopg.connect()` for database access."
- "Run migrations via `python -c 'from app.storage.connection import get_connection; ...'` not via psql."
- "Import Celery tasks from `app.celery_app` not from individual task files."

## Rules

- Only suggest patterns with confidence >= 0.5
- Patterns with >= 0.9 confidence can be auto-applied
- Content MUST be actionable and specific - include exact code, commands, or paths
- NO hedging words (might, maybe, perhaps, sometimes, usually)
- NO abstract advice - if you can't include a specific command/import/path, skip the pattern
- Detect duplicates and suggest merge instead of add
- If no patterns found, return empty array []

Return ONLY valid JSON, no markdown code blocks or explanations."""


@dataclass
class PatternSuggestion:
    """A suggested pattern from reflection."""

    action: str
    pattern_type: str
    title: str
    content: str
    rationale: str
    confidence: float
    source_diary_ids: list[str] = field(default_factory=list)
    target_pattern_id: str | None = None
    merge_pattern_ids: list[str] | None = None


@dataclass
class ReflectionResult:
    """Result of a reflection analysis."""

    suggestions: list[PatternSuggestion]
    diary_ids_processed: list[str]
    tokens_used: int
    patterns_created: list[str] = field(default_factory=list)
    patterns_auto_applied: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ReflectionService:
    """Analyze diary entries to discover and suggest patterns.

    The reflection process:
    1. Gather unreflected diary entries
    2. Get existing patterns for duplicate detection
    3. Use LLM to analyze and generate suggestions
    4. Create pending patterns from suggestions
    5. Mark diary entries as reflected
    6. Optionally auto-apply high-confidence patterns
    """

    def __init__(
        self,
        project_id: str,
        project_path: str | None = None,
        auto_apply_threshold: float = 0.9,
        model: str = "gemini-3-flash-preview",
    ):
        """Initialize the reflection service.

        Args:
            project_id: The project to reflect on.
            project_path: Path to project root (for auto-applying patterns).
            auto_apply_threshold: Min confidence for auto-apply (default 0.9).
            model: LLM model to use for analysis.
        """
        self.project_id = project_id
        self.project_path = project_path
        self.auto_apply_threshold = auto_apply_threshold
        self.model = model
        self._client: DualProviderClient | None = None

        # Initialize related services
        self.diary_service = DiaryService(project_id)
        self.pattern_service = PatternService(project_id, project_path)

    def _get_client(self) -> DualProviderClient:
        """Get or create dual provider LLM client with automatic failover."""
        if self._client is None:
            from ..agents import DualProviderClient

            self._client = DualProviderClient(
                primary="gemini",
                gemini_model="gemini-3-flash-preview",
                claude_model="claude-haiku-4-5",
            )
        return self._client

    def analyze_diary(
        self,
        limit: int = 10,
        auto_apply: bool = True,
    ) -> ReflectionResult:
        """Analyze recent diary entries and generate pattern suggestions.

        Args:
            limit: Max diary entries to analyze.
            auto_apply: Whether to auto-apply high-confidence patterns.

        Returns:
            ReflectionResult with suggestions and processing stats.
        """
        # Get unreflected diary entries
        entries = self.diary_service.get_entries(
            limit=limit,
            unreflected_only=True,
        )

        if not entries:
            logger.info("reflection_skipped: no_unreflected_entries")
            return ReflectionResult(
                suggestions=[],
                diary_ids_processed=[],
                tokens_used=0,
            )

        diary_ids = [e["id"] for e in entries]

        # Get existing patterns for duplicate detection
        existing_patterns = self.pattern_service.list_patterns(limit=100)

        # Format for prompt
        diary_text = self._format_diary_entries(entries)
        patterns_text = self._format_existing_patterns(existing_patterns)

        prompt = REFLECTION_PROMPT.format(
            diary_entries=diary_text,
            existing_patterns=patterns_text,
        )

        # Call LLM using DualProviderClient
        try:
            client = self._get_client()
            response = client.generate(prompt=prompt)

            tokens_used = response.usage.get("total_tokens", 0)

            content = response.content.strip()
            suggestions = self._parse_suggestions(content)

        except Exception as e:
            logger.error(f"reflection_llm_error: {e}")
            return ReflectionResult(
                suggestions=[],
                diary_ids_processed=diary_ids,
                tokens_used=0,
                errors=[str(e)],
            )

        # Create patterns from suggestions
        result = ReflectionResult(
            suggestions=suggestions,
            diary_ids_processed=diary_ids,
            tokens_used=tokens_used,
        )

        for suggestion in suggestions:
            try:
                pattern = self._create_pattern_from_suggestion(suggestion)
                result.patterns_created.append(pattern["id"])

                # Auto-apply high-confidence "add" patterns
                should_auto_apply = (
                    auto_apply
                    and suggestion.confidence >= self.auto_apply_threshold
                    and suggestion.action == "add"
                )
                if should_auto_apply:
                    self.pattern_service.update_status(pattern["id"], "approved")
                    self.pattern_service.apply_pattern(pattern["id"])
                    result.patterns_auto_applied.append(pattern["id"])
                    logger.info(
                        f"pattern_auto_applied: id={pattern['id']} "
                        f"confidence={suggestion.confidence}"
                    )

            except Exception as e:
                logger.error(f"pattern_creation_failed: {e}")
                result.errors.append(f"Failed to create pattern '{suggestion.title}': {e}")

        # Mark diary entries as reflected
        pattern_ids = result.patterns_created
        self.diary_service.mark_reflected(
            entry_ids=diary_ids,
            reflection_notes=f"Generated {len(suggestions)} pattern suggestions",
            patterns_generated=pattern_ids,
        )

        logger.info(
            f"reflection_complete: entries={len(diary_ids)} "
            f"suggestions={len(suggestions)} auto_applied={len(result.patterns_auto_applied)}"
        )

        return result

    def _format_diary_entries(self, entries: list[dict[str, Any]]) -> str:
        """Format diary entries for the prompt, enriched with observation details."""
        lines = []
        for entry in entries:
            lines.append(f"### Entry: {entry['id']}")
            lines.append(f"- Session: {entry['session_id']}")
            lines.append(f"- Agent: {entry['agent_type']}")
            lines.append(f"- Outcome: {entry['outcome']}")

            if entry.get("concepts"):
                lines.append(f"- Concepts: {', '.join(entry['concepts'])}")

            if entry.get("what_worked"):
                worked = entry["what_worked"]
                if isinstance(worked, str):
                    worked = json.loads(worked)
                if worked:
                    lines.append(f"- What worked: {', '.join(worked)}")

            if entry.get("what_failed"):
                failed = entry["what_failed"]
                if isinstance(failed, str):
                    failed = json.loads(failed)
                if failed:
                    lines.append(f"- What failed: {', '.join(failed)}")

            if entry.get("user_corrections"):
                corrections = entry["user_corrections"]
                if isinstance(corrections, str):
                    corrections = json.loads(corrections)
                if corrections:
                    lines.append(f"- User corrections: {', '.join(corrections)}")

            # Enrich with observation details (limit to 5 most recent per session)
            observations = self._get_session_observations(entry["session_id"], limit=5)
            if observations:
                lines.append("- Observations:")
                for obs in observations:
                    lines.append(f"  - [{obs['observation_type']}] {obs['title']}")
                    if obs.get("tool_name"):
                        lines.append(f"    Tool: {obs['tool_name']}")
                    if obs.get("narrative"):
                        # Truncate long narratives
                        narrative = obs["narrative"][:500]
                        if len(obs["narrative"]) > 500:
                            narrative += "..."
                        lines.append(f"    Details: {narrative}")
                    if obs.get("facts"):
                        facts = obs["facts"]
                        if isinstance(facts, str):
                            try:
                                facts = json.loads(facts)
                            except json.JSONDecodeError:
                                facts = {}
                        if facts:
                            # Include key facts for error observations
                            fact_strs = []
                            for k, v in list(facts.items())[:5]:
                                if v and str(v).strip():
                                    fact_strs.append(f"{k}: {v}")
                            if fact_strs:
                                lines.append(f"    Facts: {'; '.join(fact_strs)}")

            lines.append("")

        return "\n".join(lines)

    def _get_session_observations(self, session_id: str, limit: int = 5) -> list[dict[str, Any]]:
        """Get observations for a session, prioritizing error and decision types."""
        try:
            observations = get_observations_by_session(self.project_id, session_id, limit=20)
            # Prioritize error, decision, and pattern observations
            priority_types = {"error", "decision", "pattern", "correction"}
            prioritized = sorted(
                observations,
                key=lambda o: (
                    0 if o.get("observation_type") in priority_types else 1,
                    o.get("created_at", ""),
                ),
                reverse=True,
            )
            return prioritized[:limit]
        except Exception as e:
            logger.warning(f"Failed to get session observations: {e}")
            return []

    def _format_existing_patterns(self, patterns: list[dict[str, Any]]) -> str:
        """Format existing patterns for duplicate detection."""
        if not patterns:
            return "(No existing patterns)"

        lines = []
        for p in patterns:
            lines.append(f"- ID: {p['id']}")
            lines.append(f"  Title: {p['title']}")
            lines.append(f"  Content: {p['content']}")
            lines.append(f"  Status: {p['status']}")
            lines.append("")

        return "\n".join(lines)

    def _parse_suggestions(self, content: str) -> list[PatternSuggestion]:
        """Parse LLM response into PatternSuggestion objects."""
        # Try direct parse
        try:
            data = json.loads(content)
            if isinstance(data, list):
                return self._convert_to_suggestions(data)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON array from content
        json_match = re.search(r"\[[\s\S]*\]", content)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                if isinstance(data, list):
                    return self._convert_to_suggestions(data)
            except json.JSONDecodeError:
                pass

        logger.warning(f"Failed to parse reflection response: {content[:200]}...")
        return []

    def _convert_to_suggestions(self, data: list[dict[str, Any]]) -> list[PatternSuggestion]:
        """Convert parsed JSON to PatternSuggestion objects."""
        suggestions = []
        for item in data:
            try:
                suggestion = PatternSuggestion(
                    action=item.get("action", "add"),
                    pattern_type=item.get("pattern_type", "rule"),
                    title=item.get("title", "Untitled pattern"),
                    content=item.get("content", ""),
                    rationale=item.get("rationale", ""),
                    confidence=float(item.get("confidence", 0.5)),
                    source_diary_ids=item.get("source_diary_ids", []),
                    target_pattern_id=item.get("target_pattern_id"),
                    merge_pattern_ids=item.get("merge_pattern_ids"),
                )

                # Validate confidence
                if suggestion.confidence < 0.5:
                    logger.debug(f"Skipping low-confidence suggestion: {suggestion.title}")
                    continue

                suggestions.append(suggestion)

            except Exception as e:
                logger.warning(f"Failed to parse suggestion: {e}")

        return suggestions

    def _create_pattern_from_suggestion(
        self,
        suggestion: PatternSuggestion,
    ) -> dict[str, Any]:
        """Create a pattern in the database from a suggestion."""
        # Handle merge action
        if suggestion.action == "merge" and suggestion.merge_pattern_ids:
            return self.pattern_service.merge_patterns(
                pattern_ids=suggestion.merge_pattern_ids,
                merged_title=suggestion.title,
                merged_content=suggestion.content,
                rationale=suggestion.rationale,
            )

        # For add/update/remove, create with action field
        return self.pattern_service.create_pattern(
            pattern_type=suggestion.pattern_type,
            title=suggestion.title,
            content=suggestion.content,
            action=suggestion.action,
            rationale=suggestion.rationale,
            source_entry_ids=suggestion.source_diary_ids,
            confidence=suggestion.confidence,
            validate=True,  # Enforce conciseness validation
            reflected_by=self.model,
        )

    def should_trigger_reflection(
        self,
        threshold: int = 3,
    ) -> bool:
        """Check if reflection should be triggered.

        Args:
            threshold: Number of unreflected entries to trigger.

        Returns:
            True if reflection should run.
        """
        count = self.diary_service.get_unprocessed_count()
        return count >= threshold

    def get_pending_count(self) -> int:
        """Get count of pending pattern suggestions."""
        patterns = self.pattern_service.list_patterns(status="pending", limit=1000)
        return len(patterns)
