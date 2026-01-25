"""Complexity assessment service for task routing.

Assesses task complexity using heuristics and AI to determine:
- Execution tier (SIMPLE/STANDARD/COMPLEX)
- Retry limits for each tier
- Routing decisions (auto-execute vs human review)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..logging_config import get_logger

logger = get_logger(__name__)


class ComplexityTier(str, Enum):
    SIMPLE = "SIMPLE"
    STANDARD = "STANDARD"
    COMPLEX = "COMPLEX"


SIMPLE_KEYWORDS = frozenset([
    "typo",
    "typos",
    "fix",
    "update",
    "change",
    "rename",
    "add comment",
    "remove",
    "delete",
    "bump",
    "version",
    "spelling",
    "lint",
    "format",
    "style",
    "whitespace",
    "import",
    "unused",
    "dead code",
])

COMPLEX_KEYWORDS = frozenset([
    "architecture",
    "refactor",
    "redesign",
    "migration",
    "migrate",
    "security",
    "auth",
    "authentication",
    "authorization",
    "encryption",
    "database schema",
    "breaking change",
    "api change",
    "new system",
    "infrastructure",
    "performance",
    "scalability",
    "concurrency",
    "multi-tenant",
    "deployment",
    "ci/cd",
])


@dataclass
class ComplexityResult:
    """Result of complexity assessment."""

    tier: ComplexityTier
    reasoning: str
    retry_limit: int
    confidence: float
    keywords_matched: list[str]

    @property
    def should_auto_execute(self) -> bool:
        """Whether this task can be auto-executed without human approval."""
        return self.tier != ComplexityTier.COMPLEX

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier.value,
            "reasoning": self.reasoning,
            "retry_limit": self.retry_limit,
            "confidence": self.confidence,
            "keywords_matched": self.keywords_matched,
            "should_auto_execute": self.should_auto_execute,
        }


RETRY_LIMITS = {
    ComplexityTier.SIMPLE: 3,
    ComplexityTier.STANDARD: 3,
    ComplexityTier.COMPLEX: 2,
}


class ComplexityAssessor:
    """Assesses task complexity for routing decisions.

    Uses a two-stage approach:
    1. Keyword heuristics for clear cases (high confidence)
    2. AI assessment via Agent Hub for edge cases
    """

    def __init__(self) -> None:
        self._simple_pattern = self._compile_keyword_pattern(SIMPLE_KEYWORDS)
        self._complex_pattern = self._compile_keyword_pattern(COMPLEX_KEYWORDS)

    def _compile_keyword_pattern(self, keywords: frozenset[str]) -> re.Pattern[str]:
        """Compile keyword set into regex pattern for efficient matching."""
        escaped = [re.escape(kw) for kw in keywords]
        pattern = r"\b(" + "|".join(escaped) + r")\b"
        return re.compile(pattern, re.IGNORECASE)

    def _find_keywords(self, text: str, pattern: re.Pattern[str]) -> list[str]:
        """Find all matching keywords in text."""
        matches = pattern.findall(text)
        return list(set(m.lower() for m in matches))

    def assess_heuristic(self, title: str, description: str = "") -> ComplexityResult | None:
        """Assess complexity using keyword heuristics.

        Returns ComplexityResult if confident, None if AI assessment needed.
        """
        text = f"{title} {description}".lower()

        simple_matches = self._find_keywords(text, self._simple_pattern)
        complex_matches = self._find_keywords(text, self._complex_pattern)

        if complex_matches and not simple_matches:
            return ComplexityResult(
                tier=ComplexityTier.COMPLEX,
                reasoning=f"Contains complex indicators: {', '.join(complex_matches)}",
                retry_limit=RETRY_LIMITS[ComplexityTier.COMPLEX],
                confidence=0.85,
                keywords_matched=complex_matches,
            )

        if simple_matches and not complex_matches:
            return ComplexityResult(
                tier=ComplexityTier.SIMPLE,
                reasoning=f"Contains simple indicators: {', '.join(simple_matches)}",
                retry_limit=RETRY_LIMITS[ComplexityTier.SIMPLE],
                confidence=0.85,
                keywords_matched=simple_matches,
            )

        if complex_matches and simple_matches:
            return None

        word_count = len(text.split())
        if word_count < 10:
            return ComplexityResult(
                tier=ComplexityTier.SIMPLE,
                reasoning="Short description suggests simple task",
                retry_limit=RETRY_LIMITS[ComplexityTier.SIMPLE],
                confidence=0.6,
                keywords_matched=[],
            )

        return None

    async def ai_assess(self, title: str, description: str = "") -> ComplexityResult:
        """Assess complexity using AI for edge cases.

        Uses Agent Hub complete() with idea-intake-like analysis.
        """
        from .agent_hub_client import get_async_client

        prompt = f"""Assess the complexity of this task:

Title: {title}
Description: {description or "(no description)"}

Classify as:
- SIMPLE: Single-file changes, typo fixes, small tweaks (<1 hour)
- STANDARD: Multi-file changes, new features, bug fixes (1-4 hours)
- COMPLEX: Architectural changes, new systems, migrations (>4 hours)

Respond with JSON only:
{{"tier": "SIMPLE|STANDARD|COMPLEX", "reasoning": "brief explanation"}}"""

        try:
            client = get_async_client()
            response = await client.complete(
                messages=[{"role": "user", "content": prompt}],
                model="gemini-3-flash-preview",
            )

            result = self._parse_ai_response(response.content)
            return result

        except Exception as e:
            logger.warning("AI complexity assessment failed", error=str(e))
            return ComplexityResult(
                tier=ComplexityTier.STANDARD,
                reasoning=f"AI assessment failed: {e}, using default",
                retry_limit=RETRY_LIMITS[ComplexityTier.STANDARD],
                confidence=0.5,
                keywords_matched=[],
            )

    def _parse_ai_response(self, content: str) -> ComplexityResult:
        """Parse AI response into ComplexityResult."""
        try:
            json_match = re.search(r"\{[^}]+\}", content)
            if json_match:
                data = json.loads(json_match.group())
                tier_str = data.get("tier", "STANDARD").upper()
                tier = ComplexityTier[tier_str] if tier_str in ComplexityTier.__members__ else ComplexityTier.STANDARD
                reasoning = data.get("reasoning", "AI assessment")

                return ComplexityResult(
                    tier=tier,
                    reasoning=reasoning,
                    retry_limit=RETRY_LIMITS[tier],
                    confidence=0.75,
                    keywords_matched=[],
                )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Failed to parse AI response", error=str(e))

        return ComplexityResult(
            tier=ComplexityTier.STANDARD,
            reasoning="Could not parse AI response, using default",
            retry_limit=RETRY_LIMITS[ComplexityTier.STANDARD],
            confidence=0.5,
            keywords_matched=[],
        )

    async def assess(self, title: str, description: str = "") -> ComplexityResult:
        """Assess task complexity using heuristics first, then AI if needed.

        This is the main entry point for complexity assessment.
        """
        heuristic_result = self.assess_heuristic(title, description)
        if heuristic_result and heuristic_result.confidence >= 0.8:
            logger.debug(
                "Complexity assessed via heuristics",
                tier=heuristic_result.tier.value,
                confidence=heuristic_result.confidence,
            )
            return heuristic_result

        ai_result = await self.ai_assess(title, description)
        logger.debug(
            "Complexity assessed via AI",
            tier=ai_result.tier.value,
            confidence=ai_result.confidence,
        )
        return ai_result

    def assess_sync(self, title: str, description: str = "") -> ComplexityResult:
        """Synchronous version using only heuristics.

        Use this when async is not available. Falls back to STANDARD for edge cases.
        """
        heuristic_result = self.assess_heuristic(title, description)
        if heuristic_result:
            return heuristic_result

        return ComplexityResult(
            tier=ComplexityTier.STANDARD,
            reasoning="No clear indicators, defaulting to STANDARD",
            retry_limit=RETRY_LIMITS[ComplexityTier.STANDARD],
            confidence=0.5,
            keywords_matched=[],
        )
