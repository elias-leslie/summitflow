"""Code health finding classifier using Gemini Flash.

Classifies code health findings into verdicts:
- FALSE_POSITIVE: Should be added to allow list (not a real issue)
- TRUE_POSITIVE: Should create a task to fix
- NEEDS_REFACTOR: Add to backlog for future cleanup

Integrates with memory system to:
- Store classification decisions for learning
- Query past decisions to avoid redundant LLM calls
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ...constants import GEMINI_FLASH

logger = logging.getLogger(__name__)

# Memory reuse threshold - if past decision confidence >= this, reuse without LLM
MEMORY_REUSE_CONFIDENCE_THRESHOLD = 0.8


class ClassificationVerdict(str, Enum):
    """Classification verdict for code health findings."""

    FALSE_POSITIVE = "false_positive"
    TRUE_POSITIVE = "true_positive"
    NEEDS_REFACTOR = "needs_refactor"


@dataclass
class Finding:
    """A code health finding to classify."""

    file_path: str
    category: str
    pattern: str
    line_number: int | None = None
    context: str | None = None  # Surrounding code context


@dataclass
class ClassificationResult:
    """Result of classifying a code health finding."""

    verdict: ClassificationVerdict
    confidence: float
    reason: str
    suggested_action: str | None = None


def build_classification_prompt(finding: Finding) -> str:
    """Build the classification prompt for a code health finding.

    Args:
        finding: The finding to classify

    Returns:
        Structured prompt for Gemini Flash
    """
    prompt = f"""You are a code quality analyst. Classify this code health finding.

## Finding
- File: {finding.file_path}
- Category: {finding.category}
- Pattern found: {finding.pattern}
"""

    if finding.line_number:
        prompt += f"- Line: {finding.line_number}\n"

    if finding.context:
        prompt += f"""
## Code Context
```
{finding.context}
```
"""

    prompt += """
## Classification Categories

1. **FALSE_POSITIVE**: The finding is not a real issue:
   - Intentional design decision (documented)
   - Required for backward compatibility (with good reason)
   - False pattern match (not actually a problem)
   - Part of a well-maintained interface

2. **TRUE_POSITIVE**: The finding is a real issue that should be fixed:
   - Actual technical debt
   - Unintentional pattern/smell
   - Outdated code that should be updated
   - Creates maintainability problems

3. **NEEDS_REFACTOR**: The finding is real but low priority:
   - Would be nice to fix eventually
   - Not causing active problems
   - Requires larger refactoring effort

## Response Format (JSON only)

```json
{
  "verdict": "false_positive" | "true_positive" | "needs_refactor",
  "confidence": 0.0-1.0,
  "reason": "Brief explanation of your classification",
  "suggested_action": "What to do about this finding"
}
```

Respond with ONLY the JSON object, no additional text.
"""

    return prompt


class CodeHealthClassifier:
    """Classifier for code health findings using Gemini Flash.

    Integrates with memory for learning:
    - Stores classification decisions as observations
    - Queries memory for similar past decisions to avoid redundant LLM calls
    """

    def __init__(
        self,
        model: str = GEMINI_FLASH,
        project_id: str | None = None,
        enable_memory: bool = True,
    ) -> None:
        """Initialize the classifier.

        Args:
            model: Gemini model to use for classification
            project_id: Project ID for memory storage (required if enable_memory=True)
            enable_memory: Whether to use memory for learning/reuse
        """
        self.model = model
        self.project_id = project_id
        self.enable_memory = enable_memory and project_id is not None
        self._client: Any = None
        self._session_id = str(uuid.uuid4())[:8]

    def _get_client(self) -> Any:
        """Get or create the Gemini client."""
        if self._client is None:
            from google import genai

            self._client = genai.Client()
        return self._client

    def _store_classification_observation(
        self,
        finding: Finding,
        result: ClassificationResult,
    ) -> None:
        """Store classification decision as an observation for learning.

        Args:
            finding: The finding that was classified
            result: The classification result
        """
        if not self.enable_memory or not self.project_id:
            return

        try:
            from ...storage.memory import create_observation

            title = f"Code health: {finding.category} → {result.verdict.value}"
            narrative = (
                f"Classified {finding.category} in {finding.file_path} "
                f"as {result.verdict.value}. {result.reason}"
            )

            create_observation(
                project_id=self.project_id,
                session_id=f"code-health-{self._session_id}",
                agent_type="code-health-agent",
                observation_type="code_health",
                title=title,
                narrative=narrative,
                concepts=["code_health", finding.category, result.verdict.value],
                priority="low",
                confidence=result.confidence,
                files_modified=[finding.file_path],
                facts={
                    "category": finding.category,
                    "pattern": finding.pattern,
                    "verdict": result.verdict.value,
                    "reason": result.reason,
                    "suggested_action": result.suggested_action,
                },
                extracted_by="code-health-classifier",
            )

            logger.debug(
                "Stored code health observation: %s -> %s",
                finding.category,
                result.verdict.value,
            )

        except Exception as e:
            logger.warning("Failed to store classification observation: %s", e)

    def _query_memory_for_similar(
        self,
        finding: Finding,
    ) -> ClassificationResult | None:
        """Query memory for similar past classification decisions.

        Args:
            finding: The finding to look up

        Returns:
            ClassificationResult if a high-confidence match found, None otherwise
        """
        if not self.enable_memory or not self.project_id:
            return None

        try:
            from ...storage.memory import search_observations_fts

            # Search for similar past decisions
            query = f"{finding.category} {finding.file_path}"
            results = search_observations_fts(
                project_id=self.project_id,
                query=query,
                limit=5,
                query_types=["code_health"],
            )

            # Look for high-confidence match
            for obs in results:
                if obs.get("observation_type") != "code_health":
                    continue

                confidence = obs.get("confidence", 0)
                facts = obs.get("facts") or {}

                # Check if same category and high confidence
                if (
                    facts.get("category") == finding.category
                    and confidence >= MEMORY_REUSE_CONFIDENCE_THRESHOLD
                ):
                    verdict_str = facts.get("verdict", "needs_refactor")
                    try:
                        verdict = ClassificationVerdict(verdict_str)
                    except ValueError:
                        continue

                    logger.info(
                        "Memory reuse: %s -> %s (confidence: %.2f)",
                        finding.category,
                        verdict.value,
                        confidence,
                    )

                    return ClassificationResult(
                        verdict=verdict,
                        confidence=confidence,
                        reason=f"[From memory] {facts.get('reason', 'Previous decision')}",
                        suggested_action=facts.get("suggested_action"),
                    )

            return None

        except Exception as e:
            logger.warning("Failed to query memory for similar decisions: %s", e)
            return None

    def classify(self, finding: Finding) -> ClassificationResult:
        """Classify a code health finding.

        Flow:
        1. Check memory for similar past decisions with high confidence
        2. If found, reuse without LLM call
        3. Otherwise, call LLM for classification
        4. Store result in memory for future learning

        Args:
            finding: The finding to classify

        Returns:
            ClassificationResult with verdict, confidence, and reason
        """
        # Step 2 & 3: Check memory for similar past decisions
        memory_result = self._query_memory_for_similar(finding)
        if memory_result is not None:
            return memory_result

        # No memory match, use LLM
        prompt = build_classification_prompt(finding)

        try:
            client = self._get_client()

            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "temperature": 0.1,  # Low temp for consistent classification
                },
            )

            # Parse the JSON response
            result_json = json.loads(response.text)

            verdict = ClassificationVerdict(result_json.get("verdict", "needs_refactor"))
            confidence = float(result_json.get("confidence", 0.5))
            reason = result_json.get("reason", "No reason provided")
            suggested_action = result_json.get("suggested_action")

            logger.info(
                "Classified finding: %s -> %s (confidence: %.2f)",
                finding.pattern[:50],
                verdict.value,
                confidence,
            )

            result = ClassificationResult(
                verdict=verdict,
                confidence=confidence,
                reason=reason,
                suggested_action=suggested_action,
            )

            # Step 1: Store result in memory for learning
            self._store_classification_observation(finding, result)

            return result

        except json.JSONDecodeError as e:
            logger.warning("Failed to parse classifier response: %s", e)
            return ClassificationResult(
                verdict=ClassificationVerdict.NEEDS_REFACTOR,
                confidence=0.3,
                reason="Failed to parse classification response",
                suggested_action="Manual review required",
            )
        except Exception as e:
            logger.error("Classification failed: %s", e)
            return ClassificationResult(
                verdict=ClassificationVerdict.NEEDS_REFACTOR,
                confidence=0.0,
                reason=f"Classification error: {e!s}",
                suggested_action="Manual review required",
            )

    def classify_batch(self, findings: list[Finding]) -> list[tuple[Finding, ClassificationResult]]:
        """Classify multiple findings.

        Args:
            findings: List of findings to classify

        Returns:
            List of (finding, result) tuples
        """
        results = []
        for finding in findings:
            result = self.classify(finding)
            results.append((finding, result))
        return results
