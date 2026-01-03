"""Code health finding classifier using Gemini Flash.

Classifies code health findings into verdicts:
- FALSE_POSITIVE: Should be added to allow list (not a real issue)
- TRUE_POSITIVE: Should create a task to fix
- NEEDS_REFACTOR: Add to backlog for future cleanup
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ...constants import GEMINI_FLASH

logger = logging.getLogger(__name__)


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
    """Classifier for code health findings using Gemini Flash."""

    def __init__(self, model: str = GEMINI_FLASH) -> None:
        """Initialize the classifier.

        Args:
            model: Gemini model to use for classification
        """
        self.model = model
        self._client: Any = None

    def _get_client(self) -> Any:
        """Get or create the Gemini client."""
        if self._client is None:
            from google import genai

            self._client = genai.Client()
        return self._client

    def classify(self, finding: Finding) -> ClassificationResult:
        """Classify a code health finding.

        Args:
            finding: The finding to classify

        Returns:
            ClassificationResult with verdict, confidence, and reason
        """
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
            result = json.loads(response.text)

            verdict = ClassificationVerdict(result.get("verdict", "needs_refactor"))
            confidence = float(result.get("confidence", 0.5))
            reason = result.get("reason", "No reason provided")
            suggested_action = result.get("suggested_action")

            logger.info(
                "Classified finding: %s -> %s (confidence: %.2f)",
                finding.pattern[:50],
                verdict.value,
                confidence,
            )

            return ClassificationResult(
                verdict=verdict,
                confidence=confidence,
                reason=reason,
                suggested_action=suggested_action,
            )

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
