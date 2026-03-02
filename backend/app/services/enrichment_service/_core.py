"""Core enrichment logic: enrich_task, validate_enrichment, enrich_and_validate."""

from __future__ import annotations

import json
import logging
from typing import Any

from ..context_gatherer import gather_all_context
from .models import (
    AcceptanceCriterion,
    EnrichedTask,
    Subtask,
    ValidationResult,
)
from .parsers import build_enrichment_prompt, load_prompt, parse_enrichment_response

logger = logging.getLogger(__name__)


def _build_enriched_task(data: dict[str, Any]) -> EnrichedTask:
    """Construct an EnrichedTask from parsed LLM response data."""
    criteria = [
        AcceptanceCriterion(
            id=c.get("id", f"ac-{i:03d}"),
            criterion=c.get("criterion", ""),
            category=c.get("category", "correctness"),
            measurement=c.get("measurement", "test"),
            threshold=c.get("threshold"),
        )
        for i, c in enumerate(data.get("acceptance_criteria", []), start=1)
    ]

    subtasks = [
        Subtask(
            subtask_id=s.get("subtask_id", f"{i}.1"),
            phase=s.get("phase", "backend"),
            description=s.get("description", ""),
            steps=s.get("steps", []),
        )
        for i, s in enumerate(data.get("subtasks", []), start=1)
    ]

    return EnrichedTask(
        title=data.get("title", "Untitled Task"),
        objective=data.get("objective", ""),
        description=data.get("description", ""),
        task_type=data.get("task_type", "task"),
        priority=data.get("priority", 2),
        labels=data.get("labels", []),
        acceptance_criteria=criteria,
        subtasks=subtasks,
        raw_json=data,
    )


def _run_enrichment_with_retries(
    task_id: str,
    prompt: str,
    max_retries: int,
) -> EnrichedTask:
    """Call the LLM with retry logic and return an EnrichedTask."""
    from ..agent_hub_client import AgentHubLLMClient

    client = AgentHubLLMClient(agent_slug="planner")
    if not client.is_available():
        raise RuntimeError("Claude API not available")

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            logger.info("Enriching task %s (attempt %d)", task_id, attempt + 1)
            response = client.generate(
                prompt=prompt,
                temperature=0.3,
                purpose="task_enrichment",
            )
            data = parse_enrichment_response(response.content)
            enriched = _build_enriched_task(data)
            logger.info(
                "Enriched task %s: %d criteria, %d subtasks",
                task_id,
                len(enriched.acceptance_criteria),
                len(enriched.subtasks),
            )
            return enriched
        except json.JSONDecodeError as e:
            last_error = e
            logger.warning("JSON parse error on attempt %d: %s", attempt + 1, e)
            if attempt < max_retries:
                prompt += "\n\nIMPORTANT: Your previous response was not valid JSON. Return ONLY the JSON object, no other text."
        except Exception as e:
            last_error = e
            logger.error("Enrichment error on attempt %d: %s", attempt + 1, e)
            if attempt >= max_retries:
                break

    raise RuntimeError(f"Failed to enrich task after {max_retries + 1} attempts: {last_error}")


def enrich_task(
    project_id: str,
    task_id: str,
    raw_request: str,
    context: dict[str, Any] | None = None,
    max_retries: int = 2,
) -> EnrichedTask:
    """Enrich a task with AI-generated structure.

    Args:
        project_id: Project ID for context gathering
        task_id: Task ID being enriched
        raw_request: User's raw request text
        context: Pre-gathered context (optional, will gather if not provided)
        max_retries: Number of retries for parsing errors

    Returns:
        EnrichedTask with structured fields
    """
    if context is None:
        context = gather_all_context(project_id, raw_request, use_gemini=False)

    prompt = build_enrichment_prompt(raw_request, context)
    return _run_enrichment_with_retries(task_id, prompt, max_retries)


def _build_validation_prompt(enriched_task: EnrichedTask) -> str:
    """Build the validation prompt for Gemini."""
    validation_prompt = load_prompt("criteria_validation")
    task_json = json.dumps(enriched_task.raw_json, indent=2)
    return f"""{validation_prompt}

## Task to Validate

```json
{task_json}
```

## Instructions

Validate the acceptance criteria for this task.
Return ONLY valid JSON matching the output format in the prompt above."""


def validate_enrichment(enriched_task: EnrichedTask) -> ValidationResult:
    """Validate enriched task using Gemini for cross-check.

    Args:
        enriched_task: The enriched task to validate

    Returns:
        ValidationResult with feedback
    """
    prompt = _build_validation_prompt(enriched_task)
    try:
        from ..agent_hub_client import AgentHubLLMClient

        client = AgentHubLLMClient(agent_slug="auditor")
        if not client.is_available():
            logger.warning("Gemini not available for validation, skipping")
            return ValidationResult(
                valid=True,
                criteria_feedback=[],
                missing_coverage=[],
                overall_notes="Validation skipped (Gemini unavailable)",
            )

        response = client.generate(
            prompt=prompt,
            temperature=0.2,
            purpose="criteria_validation",
        )
        data = parse_enrichment_response(response.content)
        return ValidationResult(
            valid=data.get("valid", True),
            criteria_feedback=data.get("criteria_feedback", []),
            missing_coverage=data.get("missing_coverage", []),
            overall_notes=data.get("overall_notes", ""),
        )
    except Exception as e:
        logger.warning("Validation failed: %s", e)
        return ValidationResult(
            valid=True,
            criteria_feedback=[],
            missing_coverage=[],
            overall_notes=f"Validation error: {e}",
        )


def enrich_and_validate(
    project_id: str,
    task_id: str,
    raw_request: str,
) -> tuple[EnrichedTask, ValidationResult]:
    """Enrich a task and validate the results.

    Combines enrichment with Opus and validation with Gemini.

    Args:
        project_id: Project ID
        task_id: Task ID
        raw_request: User's raw request

    Returns:
        Tuple of (EnrichedTask, ValidationResult)
    """
    context = gather_all_context(project_id, raw_request, use_gemini=True)
    enriched = enrich_task(project_id, task_id, raw_request, context)
    validation = validate_enrichment(enriched)
    enriched.validation_notes = validation.missing_coverage + (
        [validation.overall_notes] if validation.overall_notes else []
    )
    return enriched, validation
