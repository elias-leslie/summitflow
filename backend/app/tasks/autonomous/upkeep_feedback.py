"""Feedback upkeep task generation."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import AGENT_HUB_URL
from app.logging_config import get_logger
from app.services._agent_hub_config import build_agent_hub_headers
from app.storage import tasks as task_store
from app.storage.task_spirit import get_task_spirit

from .upkeep_constants import (
    FEEDBACK_TIMEOUT_SECONDS,
    REQUEST_SOURCE,
    SORT_VOTES,
    SOURCE_CLIENT,
    SOURCE_FEEDBACK,
    STATUS_ACTIVE,
    TASK_TYPE_BUG,
    TASK_TYPE_TASK,
    TOOL_NAME,
)
from .upkeep_models import CreatedSignalTask, SignalTaskSpec
from .upkeep_prune import prune_obsolete_upkeep_signal_tasks
from .upkeep_signals import create_signal_task, source_key, task_exists_for_upkeep_source

logger = get_logger(__name__)

_COMPONENT_PROJECT_PREFIXES = (
    ("ah.", "agent-hub"),
    ("sf.", "summitflow"),
    ("st.", "summitflow"),
    ("dt", "summitflow"),
    ("xc.", "summitflow"),
)


def agent_hub_headers() -> dict[str, str]:
    return build_agent_hub_headers(
        request_source=REQUEST_SOURCE,
        extra_headers={
            "X-Source-Client": SOURCE_CLIENT,
            "X-Tool-Name": TOOL_NAME,
        },
    )


def feedback_task_type(feedback: dict[str, Any]) -> str | None:
    feedback_type = feedback.get("feedback_type")
    if feedback_type == "praise":
        return None
    return TASK_TYPE_BUG if feedback_type == "friction" else TASK_TYPE_TASK


def feedback_task_project_id(default_project_id: str, feedback: dict[str, Any]) -> str:
    component_id = str(feedback.get("component_id") or "")
    for prefix, project_id in _COMPONENT_PROJECT_PREFIXES:
        if component_id == prefix or component_id.startswith(prefix):
            return project_id
    return default_project_id


def fetch_feedback_items(project_id: str, limit: int) -> list[dict[str, Any]]:
    """Fetch active, unlinked Agent Hub feedback for project."""
    with httpx.Client(timeout=FEEDBACK_TIMEOUT_SECONDS) as client:
        response = client.get(
            f"{AGENT_HUB_URL}/api/feedback",
            params={
                "project_id": project_id,
                "status": STATUS_ACTIVE,
                "sort": SORT_VOTES,
                "limit": limit,
            },
            headers=agent_hub_headers(),
        )
        response.raise_for_status()
        payload = response.json()
    items = payload.get("items") if isinstance(payload, dict) else []
    return [item for item in items if isinstance(item, dict)]


def link_feedback_task(feedback_id: str, task_id: str) -> None:
    with httpx.Client(timeout=FEEDBACK_TIMEOUT_SECONDS) as client:
        response = client.patch(
            f"{AGENT_HUB_URL}/api/feedback/{feedback_id}",
            json={"linked_task_id": task_id},
            headers=agent_hub_headers(),
        )
        response.raise_for_status()


def feedback_task_spec(feedback: dict[str, Any], task_type: str, source_key_value: str) -> SignalTaskSpec:
    feedback_id = feedback.get("id")
    title = str(feedback.get("title") or feedback_id)
    parts = [
        "Routine upkeep selected this active feedback item for resolution.",
        "",
        f"Feedback ID: {feedback_id}",
        f"Component: {feedback.get('component_id') or 'unknown'}",
        f"Type: {feedback.get('feedback_type') or 'unknown'}",
        f"Votes: {feedback.get('vote_count') or 0}",
    ]
    if feedback.get("description"):
        parts.extend(["", str(feedback["description"])[:1200]])
    return SignalTaskSpec(
        source_key=source_key_value,
        signal_type=SOURCE_FEEDBACK,
        title=f"Handle feedback: {title}",
        description="\n".join(parts),
        priority=1 if title.startswith("Tool governance:") else 2 if task_type == TASK_TYPE_BUG else 3,
        task_type=task_type,
        subtask_description=f"Resolve feedback item {feedback_id}",
    )


def linked_task_matches_source(
    task_id: object,
    project_id: str,
    source_key_value: str,
) -> bool:
    """Return True when a linked task is active and still represents this feedback item."""
    if not task_id:
        return False
    task = task_store.get_task(str(task_id))
    if not task or task.get("project_id") != project_id:
        return False
    if task.get("status") in {"completed", "cancelled"}:
        return False
    spirit = get_task_spirit(str(task_id)) or {}
    context = spirit.get("context") if isinstance(spirit, dict) else {}
    upkeep = context.get("upkeep") if isinstance(context, dict) else {}
    return isinstance(upkeep, dict) and upkeep.get("source_key") == source_key_value


def feedback_task_from_item(project_id: str, feedback: dict[str, Any]) -> CreatedSignalTask | None:
    feedback_id = feedback.get("id")
    if not feedback_id:
        return None
    task_type = feedback_task_type(feedback)
    if task_type is None:
        return None
    source_key_value = source_key(SOURCE_FEEDBACK, feedback_id)
    task_project_id = feedback_task_project_id(project_id, feedback)
    existing_task_id = task_exists_for_upkeep_source(task_project_id, source_key_value)
    if existing_task_id:
        if feedback.get("linked_task_id") != existing_task_id:
            try:
                link_feedback_task(str(feedback_id), existing_task_id)
            except Exception as exc:
                logger.warning(
                    "feedback_relink_failed",
                    feedback_id=feedback_id,
                    task_id=existing_task_id,
                    error=str(exc),
                )
        return None
    if linked_task_matches_source(feedback.get("linked_task_id"), task_project_id, source_key_value):
        return None
    task_id = create_signal_task(task_project_id, feedback_task_spec(feedback, task_type, source_key_value))
    try:
        link_feedback_task(str(feedback_id), task_id)
    except Exception as exc:
        logger.warning("feedback_link_failed", feedback_id=feedback_id, task_id=task_id, error=str(exc))
    return CreatedSignalTask(task_id=task_id, source_key=source_key_value)


def create_feedback_tasks(project_id: str, limit: int) -> list[str]:
    """Create autonomous tasks for top active feedback items."""
    created: list[str] = []
    feedback_items = fetch_feedback_items(project_id, max(limit, 200))
    active_source_keys = {
        source_key(SOURCE_FEEDBACK, feedback["id"])
        for feedback in feedback_items
        if feedback.get("id") and feedback_task_type(feedback) is not None
    }
    prune_obsolete_upkeep_signal_tasks(project_id, SOURCE_FEEDBACK, active_source_keys)
    for feedback in feedback_items:
        created_task = feedback_task_from_item(project_id, feedback)
        if created_task is None:
            continue
        created.append(created_task.task_id)
        if len(created) >= limit:
            break
    return created
