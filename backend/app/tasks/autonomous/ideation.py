"""Ideation stage: flesh out raw ideas into structured task descriptions.

Uses the ideator agent to expand crowdsourced ideas with:
- Scope definition and boundaries
- Suggested acceptance criteria
- Dependency analysis
- Complexity estimation
"""

from __future__ import annotations

import json
from typing import Any

from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...services.task_second_opinion import ensure_second_opinion_tracking
from ...storage import log_task_event
from ...storage import tasks as task_store
from ...storage.task_spirit import upsert_task_spirit

logger = get_logger(__name__)


def _build_ideation_prompt(title: str, description: str) -> str:
    """Build the prompt for the ideator agent."""
    return (
        f"You are expanding a raw idea into a well-defined task.\n\n"
        f"## Raw Idea\n"
        f"Title: {title}\n"
        f"Description: {description or '(none provided)'}\n\n"
        f"## Instructions\n"
        f"Analyze this idea and produce a structured task definition. "
        f"Reply with JSON:\n"
        f'{{"objective": "clear 1-2 sentence objective",'
        f' "scope": "what is in scope and out of scope",'
        f' "acceptance_criteria": ["criterion 1", "criterion 2", ...],'
        f' "suggested_type": "feature|bug|refactor|task|debt",'
        f' "complexity": "SIMPLE|STANDARD|COMPLEX",'
        f' "dependencies": ["any known dependencies or blockers"],'
        f' "enriched_description": "expanded description with technical details"}}'
    )


def _apply_ideation_result(
    task_id: str, result: dict[str, Any]
) -> dict[str, Any]:
    """Persist ideation result and return success response."""
    upsert_task_spirit(
        task_id,
        context=result.get("scope", ""),
    )

    updates: dict[str, Any] = {
        "enrichment_status": "accepted",
        "enriched_by": "ideator",
        "description": result.get("enriched_description") or result["objective"],
    }
    if result.get("suggested_type"):
        updates["task_type"] = result["suggested_type"]
    if result.get("complexity"):
        updates["complexity"] = result["complexity"]

    task_store.update_task(task_id, **updates)
    updated_task = task_store.get_task(task_id)
    if updated_task:
        ensure_second_opinion_tracking(task_id, updated_task, source="ideation")

    log_task_event(
        task_id,
        f"Ideation complete: {result['objective'][:200]}",
    )
    logger.info("Ideation succeeded", task_id=task_id)

    return {
        "task_id": task_id,
        "status": "ideated",
        "objective": result["objective"],
        "complexity": result.get("complexity", "STANDARD"),
    }


def _call_ideator_agent(
    task_id: str, project_id: str, prompt: str
) -> dict[str, Any]:
    """Call the ideator agent and return a structured response dict."""
    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            agent_slug="ideator",
            project_id=project_id,
            use_memory=True,
            memory_group_id=f"project:{project_id}",
        )
        result = _parse_ideation_response(response.content)
        if result.get("objective"):
            return _apply_ideation_result(task_id, result)
        log_task_event(task_id, "Ideation: could not produce clear objective")
        return {"task_id": task_id, "status": "unclear", "reason": "no_objective_produced"}
    except Exception as e:
        logger.warning("Ideation failed", task_id=task_id, error=str(e))
        log_task_event(task_id, f"Ideation failed: {str(e)[:200]}")
        return {"task_id": task_id, "status": "error", "error": str(e)}


def ideate_task(task_id: str, project_id: str) -> dict[str, Any]:
    """Flesh out a raw idea into a structured task description.

    Uses the ideator agent to expand a brief idea into a well-defined task
    with scope, acceptance criteria, and complexity estimate.

    After successful ideation, the task moves to triage.

    Args:
        task_id: The task ID to ideate on
        project_id: The project ID

    Returns:
        Ideation result with enriched task details
    """
    task = task_store.get_task(task_id)
    if not task:
        logger.warning("Task not found for ideation", task_id=task_id)
        return {"task_id": task_id, "status": "error", "reason": "task_not_found"}

    prompt = _build_ideation_prompt(
        title=task.get("title", ""),
        description=task.get("description", ""),
    )
    return _call_ideator_agent(task_id, project_id, prompt)


def _parse_ideation_response(content: str) -> dict[str, Any]:
    """Parse ideator agent response, extracting JSON from the response."""
    # Try to find JSON in the response
    try:
        # Look for JSON block
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            result: dict[str, Any] = json.loads(content[start:end])
            return result
    except json.JSONDecodeError:
        pass

    # Fallback: treat the whole response as the objective
    return {"objective": content[:500], "enriched_description": content}
