"""Code health finding classifier using Agent Hub.

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
from dataclasses import dataclass
from enum import StrEnum

from ..agent_hub_client import AgentHubLLMClient

logger = logging.getLogger(__name__)

# Memory reuse threshold - if past decision confidence >= this, reuse without LLM
MEMORY_REUSE_CONFIDENCE_THRESHOLD = 0.8


class ClassificationVerdict(StrEnum):
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
    """Classifier for code health findings using Agent Hub.

    Integrates with memory for learning:
    - Stores classification decisions as observations
    - Queries memory for similar past decisions to avoid redundant LLM calls
    """

    def __init__(
        self,
        agent_slug: str = "analyst",
        project_id: str | None = None,
        enable_memory: bool = True,
    ) -> None:
        """Initialize the classifier.

        Args:
            agent_slug: Agent slug for classification routing (default: analyst)
            project_id: Project ID for memory storage (required if enable_memory=True)
            enable_memory: Whether to use memory for learning/reuse
        """
        self.agent_slug = agent_slug
        self.project_id = project_id or "summitflow"
        self.enable_memory = enable_memory
        self._client: AgentHubLLMClient | None = None

    def _get_client(self) -> AgentHubLLMClient:
        """Get or create the Agent Hub client."""
        if self._client is None:
            self._client = AgentHubLLMClient(
                agent_slug=self.agent_slug,
                project_id=self.project_id,
                use_memory=self.enable_memory,
            )
        return self._client

    def _store_classification_observation(
        self,
        finding: Finding,
        result: ClassificationResult,
    ) -> None:
        """Store classification decision as an observation for learning.

        Memory system removed - this is now a no-op.
        Memory functionality moved to Agent Hub with Graphiti.
        """
        # Memory system removed - no-op
        pass

    def _query_memory_for_similar(
        self,
        finding: Finding,
    ) -> ClassificationResult | None:
        """Query memory for similar past classification decisions.

        Memory system removed - always returns None.
        Memory functionality moved to Agent Hub with Graphiti.
        """
        # Memory system removed - always returns None
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

            response = client.generate(
                prompt=prompt,
                temperature=0.1,  # Low temp for consistent classification
                purpose="code_health_classification",
            )

            # Parse the JSON response
            result_json = json.loads(response.content)

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
