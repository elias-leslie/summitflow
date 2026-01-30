"""Task discussion functionality for enrichment service."""

from __future__ import annotations

import json
import logging
from typing import Any

from .models import DiscussionResponse
from .parsers import load_prompt, parse_enrichment_response

logger = logging.getLogger(__name__)


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

    if current_task is None:
        from ...storage.tasks import get_task

        current_task = get_task(task_id)
        if current_task is None:
            raise ValueError(f"Task {task_id} not found")

    discussion_prompt = load_prompt("task_discussion")

    history = history or []
    conversation = "\n".join(
        f"{'User' if h.get('role') == 'user' else 'Assistant'}: {h.get('content', '')}"
        for h in history
    )

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

    from ..agent_hub_client import AgentHubLLMClient

    client = AgentHubLLMClient(agent_slug="planner")
    if not client.is_available():
        raise RuntimeError("Claude API not available")

    try:
        response = client.generate(
            prompt=prompt,
            temperature=0.5,
            purpose="task_discussion",
        )

        data = parse_enrichment_response(response.content)

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
