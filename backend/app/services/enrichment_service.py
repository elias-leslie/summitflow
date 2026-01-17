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

from ..constants import CLAUDE_OPUS_FULL, DEFAULT_GEMINI_MODEL
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

    result: dict[str, Any] = json.loads(text)
    return result


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

    # Import Agent Hub client
    from .agent_hub_client import AgentHubLLMClient

    client = AgentHubLLMClient(model=CLAUDE_OPUS_FULL)
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
                purpose="task_enrichment",
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

    # Import Agent Hub client for Gemini
    try:
        from .agent_hub_client import AgentHubLLMClient

        client = AgentHubLLMClient(model=DEFAULT_GEMINI_MODEL)
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
            purpose="criteria_validation",
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
        enriched_by=CLAUDE_OPUS_FULL,
        enriched_at=datetime.now(UTC),
    )

    if updated is None:
        raise ValueError(f"Task {task_id} not found")

    # Replace subtasks (this cascades to delete steps via FK)
    delete_subtasks_for_task(task_id)
    subtask_dicts = [
        {
            "subtask_id": s.subtask_id,
            "phase": s.phase,
            "description": s.description,
            "steps": s.steps,  # bulk_create_subtasks creates rows in task_subtask_steps
        }
        for s in enriched.subtasks
    ]
    # bulk_create_subtasks auto-creates steps in normalized table
    bulk_create_subtasks(task_id, subtask_dicts)

    total_steps = sum(len(s.steps) for s in enriched.subtasks)
    logger.info(
        "Applied enrichment to task %s: %d subtasks, %d steps created",
        task_id,
        len(subtask_dicts),
        total_steps,
    )

    return updated


@dataclass
class DiscussionResponse:
    """Response from a task discussion."""

    response: str
    changes_made: list[str]
    updated_task: dict[str, Any] | None


def discuss_task(
    project_id: str,
    task_id: str,
    message: str,
    history: list[dict[str, str]] | None = None,
    current_task: dict[str, Any] | None = None,
) -> DiscussionResponse:
    """Have a discussion about a task with AI.

    Args:
        project_id: Project ID
        task_id: Task ID being discussed
        message: User's message
        history: Previous discussion messages (role, content pairs)
        current_task: Current task state (fetched if not provided)

    Returns:
        DiscussionResponse with AI response and any task changes
    """
    # Load current task if not provided
    if current_task is None:
        from ..storage.tasks import get_task

        current_task = get_task(task_id)
        if current_task is None:
            raise ValueError(f"Task {task_id} not found")

    # Load discussion prompt
    discussion_prompt = _load_prompt("task_discussion")

    # Build conversation history
    history = history or []
    conversation = "\n".join(
        f"{'User' if h.get('role') == 'user' else 'Assistant'}: {h.get('content', '')}"
        for h in history
    )

    # Build prompt
    task_json = json.dumps(current_task, indent=2, default=str)
    prompt = f"""{discussion_prompt}

## Current Task State

```json
{task_json}
```

## Conversation History

{conversation if conversation else "(No previous messages)"}

## Current Message

User: {message}

## Instructions

Respond to the user's message about this task.
Return ONLY valid JSON matching the response format in the prompt above."""

    # Call Opus via Agent Hub
    from .agent_hub_client import AgentHubLLMClient

    client = AgentHubLLMClient(model=CLAUDE_OPUS_FULL)
    if not client.is_available():
        raise RuntimeError("Claude API not available")

    try:
        response = client.generate(
            prompt=prompt,
            max_tokens=4096,
            temperature=0.5,
            purpose="task_discussion",
        )

        data = _parse_enrichment_response(response.content)

        return DiscussionResponse(
            response=data.get("response", "I'm not sure how to respond to that."),
            changes_made=data.get("changes_made", []),
            updated_task=data.get("updated_task"),
        )

    except Exception as e:
        logger.error("Discussion failed: %s", e)
        return DiscussionResponse(
            response=f"I encountered an error: {e}. Please try rephrasing your message.",
            changes_made=[],
            updated_task=None,
        )


def apply_discussion_changes(
    task_id: str,
    updated_task: dict[str, Any],
) -> dict[str, Any]:
    """Apply changes from discussion to a task.

    Args:
        task_id: Task ID to update
        updated_task: Updated task data from discussion

    Returns:
        Updated task dict from database
    """
    from ..storage.tasks import update_task

    # Extract fields that can be updated
    updatable_fields = [
        "title",
        "objective",
        "description",
        "priority",
        "labels",
        "task_type",
    ]

    fields_to_update = {
        k: v for k, v in updated_task.items() if k in updatable_fields and v is not None
    }

    if not fields_to_update:
        logger.info("No updatable fields in discussion changes for task %s", task_id)
        from ..storage.tasks import get_task

        return get_task(task_id) or {}

    # Mark as discussing
    fields_to_update["enrichment_status"] = "discussing"

    updated = update_task(task_id, **fields_to_update)
    if updated is None:
        raise ValueError(f"Task {task_id} not found")

    logger.info(
        "Applied discussion changes to task %s: %s",
        task_id,
        list(fields_to_update.keys()),
    )

    return updated
