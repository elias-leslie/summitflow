"""Task discussion functionality for enrichment service."""

from __future__ import annotations

import json
import logging
from typing import Any

from ..context_gatherer import collect_precision_code_search_context
from .models import DiscussionResponse
from .parsers import load_prompt, parse_enrichment_response

logger = logging.getLogger(__name__)


def _fetch_task_if_needed(task_id: str, current_task: dict[str, Any] | None) -> dict[str, Any]:
    """Fetch the task from storage if not already provided.

    Args:
        task_id: Task ID to fetch
        current_task: Existing task dict, or None to trigger a fetch

    Returns:
        Task dict from storage

    Raises:
        ValueError: If the task is not found
    """
    if current_task is not None:
        return current_task
    from ...storage.tasks import get_task

    task = get_task(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")
    return task


def _build_conversation_string(history: list[dict[str, str]]) -> str:
    """Format conversation history into a readable string.

    Args:
        history: List of role/content message dicts

    Returns:
        Formatted conversation string, or empty string if no history
    """
    return "\n".join(
        f"{'User' if h.get('role') == 'user' else 'Assistant'}: {h.get('content', '')}"
        for h in history
    )


def _build_discussion_prompt(
    discussion_prompt: str,
    task_json: str,
    conversation: str,
    message: str,
    precision_context: str = "",
) -> str:
    """Assemble the full discussion prompt sent to the LLM.

    Args:
        discussion_prompt: Base prompt loaded from file
        task_json: JSON-serialised current task state
        conversation: Formatted conversation history string
        message: Current user message

    Returns:
        Complete prompt string
    """
    conversation_section = conversation if conversation else "(No previous messages)"
    precision_block = (
        f"\n## Precision Code Search\n\n{precision_context}\n"
        if precision_context
        else ""
    )
    return f"""{discussion_prompt}

## Current Task State

```json
{task_json}
```
{precision_block}

## Conversation History

{conversation_section}

## Current Message

User: {message}

## Instructions

Respond to the user's message about this task.
Return ONLY valid JSON matching the response format in the prompt above."""


def _call_llm_for_discussion(prompt: str) -> dict[str, Any]:
    """Send the discussion prompt to the LLM and parse the response.

    Args:
        prompt: Fully assembled prompt string

    Returns:
        Parsed response data dict

    Raises:
        RuntimeError: If the Claude API is not available
    """
    from ..agent_hub_client import AgentHubLLMClient

    client = AgentHubLLMClient(agent_slug="planner")
    if not client.is_available():
        raise RuntimeError("Claude API not available")

    response = client.generate(
        prompt=prompt,
        temperature=0.5,
        purpose="task_discussion",
    )
    return parse_enrichment_response(response.content)


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
    _ = project_id

    current_task = _fetch_task_if_needed(task_id, current_task)
    discussion_prompt = load_prompt("task_discussion")

    conversation = _build_conversation_string(history or [])
    task_json = json.dumps(current_task, indent=2, default=str)
    precision_context = collect_precision_code_search_context(
        project_id,
        [
            message,
            str(current_task.get("title", "")),
            str(current_task.get("description", "")),
        ],
        budget_tokens=1200,
    ).prompt_context
    prompt = _build_discussion_prompt(
        discussion_prompt,
        task_json,
        conversation,
        message,
        precision_context,
    )

    try:
        data = _call_llm_for_discussion(prompt)
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
    from ...storage.tasks import update_task

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
        from ...storage.tasks import get_task

        return get_task(task_id) or {}

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


__all__ = ["apply_discussion_changes", "discuss_task"]
