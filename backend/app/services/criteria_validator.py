"""Criteria validation service using Opus for quality evaluation.

Validates acceptance criteria against quality checklist to ensure
they are specific, measurable, and verifiable.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..constants import CLAUDE_OPUS

if TYPE_CHECKING:
    from ..schemas.tasks import AcceptanceCriterion

logger = logging.getLogger(__name__)

# Prompt template for Opus criteria validation
CRITERIA_QUALITY_PROMPT = """You are an expert code reviewer evaluating acceptance criteria for software tasks.

OBJECTIVE: {objective}

CRITERIA TO EVALUATE:
{criteria_json}

For EACH criterion, evaluate against this checklist:
1. SPECIFIC: Does it describe a concrete, unambiguous behavior or outcome?
2. MEASURABLE: Can it be verified with a yes/no answer (not "somewhat" or "mostly")?
3. TESTABLE: Can an automated test verify this criterion?
4. THRESHOLD: If performance-related, does it specify a concrete threshold (e.g., "<200ms", "100%")?
5. INDEPENDENT: Can this criterion be verified without relying on other criteria?

Return a JSON object with this exact structure:
{{
  "results": [
    {{
      "criterion_id": "ac-001",
      "pass": true|false,
      "issues": ["Issue 1 if any", "Issue 2 if any"],
      "suggestion": "How to improve if failed"
    }}
  ],
  "overall_valid": true|false
}}

CRITICAL RULES:
- A criterion FAILS if ANY checklist item is not met
- Vague words like "fast", "efficient", "good" always FAIL
- Performance criteria without thresholds always FAIL
- Return ONLY the JSON object, no other text
"""


@dataclass
class CriterionValidationResult:
    """Result for a single criterion validation."""

    criterion_id: str
    valid: bool
    issues: list[str] = field(default_factory=list)
    suggestion: str | None = None


@dataclass
class ValidationResult:
    """Result of validating all criteria."""

    valid: bool
    failures: list[CriterionValidationResult] = field(default_factory=list)
    raw_response: str | None = None


def validate_criteria(
    objective: str,
    criteria: list[AcceptanceCriterion],
) -> ValidationResult:
    """Validate acceptance criteria using Opus.

    Args:
        objective: The task objective (provides context)
        criteria: List of AcceptanceCriterion to validate

    Returns:
        ValidationResult with overall validity and per-criterion failures
    """
    if not criteria:
        return ValidationResult(valid=True, failures=[])

    # Import here to avoid circular imports
    from .agent_hub_client import get_agent

    # Format criteria for prompt
    criteria_data = [
        {
            "id": c.id,
            "criterion": c.criterion,
            "category": c.category,
            "measurement": c.measurement,
            "threshold": c.threshold,
        }
        for c in criteria
    ]
    criteria_json = json.dumps(criteria_data, indent=2)

    prompt = CRITERIA_QUALITY_PROMPT.format(objective=objective, criteria_json=criteria_json)

    try:
        # Use Opus for validation (highest quality judgment)
        agent = get_agent("claude", model=CLAUDE_OPUS)
        response = agent.generate(prompt, purpose="criteria_validation")

        if not response.content:
            logger.warning("Empty response from Opus validation")
            return ValidationResult(
                valid=False,
                failures=[
                    CriterionValidationResult(
                        criterion_id="all",
                        valid=False,
                        issues=["Validation service returned empty response"],
                    )
                ],
                raw_response=None,
            )

        # Parse JSON response
        result_json = _extract_json(response.content)
        if not result_json:
            logger.warning(f"Could not parse Opus response: {response.content[:200]}")
            return ValidationResult(
                valid=False,
                failures=[
                    CriterionValidationResult(
                        criterion_id="all",
                        valid=False,
                        issues=["Could not parse validation response"],
                    )
                ],
                raw_response=response.content,
            )

        # Convert to ValidationResult
        failures: list[CriterionValidationResult] = []
        for result in result_json.get("results", []):
            if not result.get("pass", False):
                failures.append(
                    CriterionValidationResult(
                        criterion_id=result.get("criterion_id", "unknown"),
                        valid=False,
                        issues=result.get("issues", []),
                        suggestion=result.get("suggestion"),
                    )
                )

        overall_valid = result_json.get("overall_valid", len(failures) == 0)

        return ValidationResult(
            valid=overall_valid, failures=failures, raw_response=response.content
        )

    except Exception as e:
        logger.exception("Error validating criteria with Opus")
        return ValidationResult(
            valid=False,
            failures=[
                CriterionValidationResult(
                    criterion_id="all",
                    valid=False,
                    issues=[f"Validation error: {e!s}"],
                )
            ],
        )


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract JSON object from text response.

    Handles cases where response includes markdown code blocks or extra text.
    """
    import re

    # Try to find JSON in markdown code blocks first
    code_block_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if code_block_match:
        try:
            result: dict[str, Any] = json.loads(code_block_match.group(1))
            return result
        except json.JSONDecodeError:
            pass

    # Try to find raw JSON object
    json_match = re.search(r"\{[\s\S]*\}", text)
    if json_match:
        try:
            result2: dict[str, Any] = json.loads(json_match.group(0))
            return result2
        except json.JSONDecodeError:
            pass

    return None
