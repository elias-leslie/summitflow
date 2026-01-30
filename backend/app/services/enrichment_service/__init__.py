"""Enrichment Service - AI-powered task enrichment using Opus and Gemini.

This service transforms raw user requests into structured tasks with
objectives, acceptance criteria, and implementation subtasks.

This module is organized as follows:
- models.py: Data models (AcceptanceCriterion, Subtask, EnrichedTask, etc.)
- parsers.py: Prompt loading and response parsing
- discussion.py: Task discussion functionality
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from ...constants import CLAUDE_OPUS_FULL
from ..context_gatherer import gather_all_context
from .discussion import apply_discussion_changes, discuss_task
from .models import (
    AcceptanceCriterion,
    DiscussionResponse,
    EnrichedTask,
    Subtask,
    ValidationResult,
)
from .parsers import build_enrichment_prompt, load_prompt, parse_enrichment_response

logger = logging.getLogger(__name__)


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

            enriched = EnrichedTask(
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

            logger.info(
                "Enriched task %s: %d criteria, %d subtasks",
                task_id,
                len(criteria),
                len(subtasks),
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


def validate_enrichment(enriched_task: EnrichedTask) -> ValidationResult:
    """Validate enriched task using Gemini for cross-check.

    Args:
        enriched_task: The enriched task to validate

    Returns:
        ValidationResult with feedback
    """
    validation_prompt = load_prompt("criteria_validation")

    task_json = json.dumps(enriched_task.raw_json, indent=2)

    prompt = f"""{validation_prompt}

## Task to Validate

```json
{task_json}
```

## Instructions

Validate the acceptance criteria for this task.
Return ONLY valid JSON matching the output format in the prompt above."""

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


def apply_enrichment_to_task(
    task_id: str,
    enriched: EnrichedTask,
) -> dict[str, Any]:
    """Apply enrichment results to a task in the database.

    Args:
        task_id: Task ID to update
        enriched: Enriched task data

    Returns:
        Updated task dict
    """
    from ...storage.subtasks import bulk_create_subtasks, delete_subtasks_for_task
    from ...storage.tasks import update_task

    updated = update_task(
        task_id,
        title=enriched.title,
        objective=enriched.objective,
        description=enriched.description,
        task_type=enriched.task_type,
        priority=enriched.priority,
        labels=enriched.labels,
        enrichment_status="review",
        enriched_by=CLAUDE_OPUS_FULL,
        enriched_at=datetime.now(UTC),
    )

    if updated is None:
        raise ValueError(f"Task {task_id} not found")

    delete_subtasks_for_task(task_id)
    subtask_dicts = [
        {
            "subtask_id": s.subtask_id,
            "phase": s.phase,
            "description": s.description,
            "steps": s.steps,
        }
        for s in enriched.subtasks
    ]
    bulk_create_subtasks(task_id, subtask_dicts)

    total_steps = sum(len(s.steps) for s in enriched.subtasks)
    logger.info(
        "Applied enrichment to task %s: %d subtasks, %d steps created",
        task_id,
        len(subtask_dicts),
        total_steps,
    )

    return updated


__all__ = [
    "AcceptanceCriterion",
    "DiscussionResponse",
    "EnrichedTask",
    "Subtask",
    "ValidationResult",
    "apply_discussion_changes",
    "apply_enrichment_to_task",
    "discuss_task",
    "enrich_and_validate",
    "enrich_task",
    "validate_enrichment",
]
