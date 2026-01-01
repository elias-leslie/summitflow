"""Enrichment Service - AI-powered task enrichment using Opus and Gemini.

This service transforms raw user requests into structured tasks with
objectives, acceptance criteria, and implementation subtasks.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .context_gatherer import format_context_for_prompt, gather_all_context

logger = logging.getLogger(__name__)

# Load prompts from files
PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    """Load a prompt from the prompts directory."""
    path = PROMPTS_DIR / f"{name}.md"
    if path.exists():
        return path.read_text()
    logger.warning("Prompt file not found: %s", path)
    return ""


@dataclass
class AcceptanceCriterion:
    """A single acceptance criterion."""

    id: str
    criterion: str
    category: str = "correctness"
    measurement: str = "test"
    threshold: str | None = None


@dataclass
class Subtask:
    """A single implementation subtask."""

    subtask_id: str
    phase: str
    description: str
    steps: list[str] = field(default_factory=list)


@dataclass
class EnrichedTask:
    """Result of task enrichment."""

    title: str
    objective: str
    description: str
    task_type: str
    priority: int
    labels: list[str]
    acceptance_criteria: list[AcceptanceCriterion]
    subtasks: list[Subtask]
    raw_json: dict[str, Any]
    validation_notes: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Result of enrichment validation."""

    valid: bool
    criteria_feedback: list[dict[str, Any]]
    missing_coverage: list[str]
    overall_notes: str


def _parse_enrichment_response(response_text: str) -> dict[str, Any]:
    """Parse JSON from LLM response text.

    Handles markdown code blocks and extracts JSON.
    """
    text = response_text.strip()

    # Remove markdown code block if present
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]

    if text.endswith("```"):
        text = text[:-3]

    text = text.strip()

    return json.loads(text)


def _build_enrichment_prompt(raw_request: str, context: dict[str, Any]) -> str:
    """Build the full prompt for task enrichment."""
    system_prompt = _load_prompt("task_enrichment")
    formatted_context = format_context_for_prompt(context)

    return f"""{system_prompt}

## Project Context

{formatted_context}

## User's Request

{raw_request}

## Instructions

Based on the user's request and project context, generate a structured task.
Return ONLY valid JSON matching the schema in the prompt above.
Do not include any explanation or markdown outside the JSON."""


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
    # Gather context if not provided
    if context is None:
        context = gather_all_context(project_id, raw_request, use_gemini=False)

    # Build the prompt
    prompt = _build_enrichment_prompt(raw_request, context)

    # Import Claude client
    from .agents.claude import ClaudeClient

    client = ClaudeClient(model="claude-opus-4-5-20251101")
    if not client.is_available():
        raise RuntimeError("Claude API not available")

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            logger.info("Enriching task %s (attempt %d)", task_id, attempt + 1)

            response = client.generate(
                prompt=prompt,
                max_tokens=4096,
                temperature=0.3,
            )

            # Parse response
            data = _parse_enrichment_response(response.content)

            # Build EnrichedTask
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
                # Add clarification to prompt for retry
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
    validation_prompt = _load_prompt("criteria_validation")

    # Build validation request
    task_json = json.dumps(enriched_task.raw_json, indent=2)

    prompt = f"""{validation_prompt}

## Task to Validate

```json
{task_json}
```

## Instructions

Validate the acceptance criteria for this task.
Return ONLY valid JSON matching the output format in the prompt above."""

    # Import Gemini client
    try:
        from .agents.gemini import GeminiClient

        client = GeminiClient(model="gemini-3-flash-preview")
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
            max_tokens=2000,
            temperature=0.2,
        )

        data = _parse_enrichment_response(response.content)

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
    # Gather context once
    context = gather_all_context(project_id, raw_request, use_gemini=True)

    # Enrich with Opus
    enriched = enrich_task(project_id, task_id, raw_request, context)

    # Validate with Gemini
    validation = validate_enrichment(enriched)

    # Add validation notes to enriched task
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
    from ..storage.subtasks import bulk_create_subtasks, delete_subtasks_for_task
    from ..storage.tasks import update_task

    # Update task fields
    updated = update_task(
        task_id,
        title=enriched.title,
        objective=enriched.objective,
        description=enriched.description,
        task_type=enriched.task_type,
        priority=enriched.priority,
        labels=enriched.labels,
        enrichment_status="review",
        enriched_by="claude-opus-4.5",
        enriched_at=datetime.now(UTC),
    )

    if updated is None:
        raise ValueError(f"Task {task_id} not found")

    # Replace subtasks
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

    logger.info(
        "Applied enrichment to task %s: %d subtasks created",
        task_id,
        len(subtask_dicts),
    )

    return updated
