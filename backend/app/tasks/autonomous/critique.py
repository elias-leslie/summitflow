"""Autonomous task-shape critique for high-risk task packages."""

from __future__ import annotations

import json
from typing import Any

from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...services.task_execution_readiness import sync_task_execution_readiness
from ...services.task_second_opinion import (
    get_second_opinion_requirement,
    parse_second_opinion_response,
    persist_second_opinion,
)
from ...storage import log_task_event
from ...storage import tasks as task_store
from ...storage.subtasks import get_subtasks_for_task
from ...storage.task_spirit import get_task_spirit

logger = get_logger(__name__)

_DEFAULT_AGENT = "specifier"
_CONTEXT_KEYS = (
    "files_to_modify",
    "files_to_create",
    "risks",
    "references",
    "testing_strategy",
    "execution_contract",
)


def _serialize_step(step: dict[str, Any]) -> dict[str, Any]:
    serialized = {
        "step_number": step.get("step_number"),
        "description": step.get("description"),
        "depends_on": step.get("depends_on") or [],
        "spec": step.get("spec"),
    }
    return {key: value for key, value in serialized.items() if value not in (None, [], {})}


def _serialize_context(context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(context, dict):
        return {}
    serialized = {
        key: context.get(key)
        for key in _CONTEXT_KEYS
        if context.get(key) not in (None, [], {})
    }
    second_opinion = context.get("second_opinion")
    if isinstance(second_opinion, dict):
        serialized["second_opinion"] = {
            key: second_opinion.get(key)
            for key in ("required", "stage", "status", "summary", "findings", "missing_requirements")
            if second_opinion.get(key) not in (None, "", [], {})
        }
    return serialized


def _serialize_subtask(subtask: dict[str, Any]) -> dict[str, Any]:
    serialized = {
        "subtask_id": subtask.get("subtask_id"),
        "phase": subtask.get("phase"),
        "subtask_type": subtask.get("subtask_type"),
        "status": subtask.get("status"),
        "depends_on": subtask.get("depends_on") or [],
        "description": subtask.get("description"),
        "steps": [
            _serialize_step(step)
            for step in (subtask.get("steps_from_table") or subtask.get("steps") or [])
            if isinstance(step, dict)
        ],
    }
    return {key: value for key, value in serialized.items() if value not in (None, [], {})}


def _build_review_packet(
    task: dict[str, Any],
    spirit: dict[str, Any] | None,
    subtasks: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "task": {
            "id": task["id"],
            "project_id": task["project_id"],
            "title": task.get("title"),
            "description": task.get("description"),
            "priority": task.get("priority"),
            "task_type": task.get("task_type"),
            "complexity": task.get("complexity") or (spirit or {}).get("complexity"),
            "labels": task.get("labels") or [],
        },
        "spirit": {
            "objective": (spirit or {}).get("objective") or task.get("objective"),
            "spirit_anti": (spirit or {}).get("spirit_anti") or task.get("spirit_anti"),
            "decisions": (spirit or {}).get("decisions") or task.get("decisions") or [],
            "constraints": (spirit or {}).get("constraints") or task.get("constraints") or [],
            "done_when": (spirit or {}).get("done_when") or task.get("done_when") or [],
            "context": _serialize_context((spirit or {}).get("context") or task.get("context")),
        },
        "subtasks": [_serialize_subtask(subtask) for subtask in subtasks],
    }


def _build_request_message(packet: dict[str, Any]) -> str:
    return (
        "Stage: task_shape\n"
        "Stage lens: Judge whether implementation can start safely from this package. "
        "Focus on missing contract, hidden dependencies, ambiguous precedence, "
        "verification gaps, and simpler paths.\n"
        "Skip categories that are not materially implicated by this task package. "
        "Mention rollout, migration, or monitoring only when materially affected.\n\n"
        "Return strict JSON only with this shape:\n"
        "{\n"
        '  "verdict": "APPROVED" | "NEEDS_REVISION",\n'
        '  "summary": "1-2 sentence assessment",\n'
        '  "missing_requirements": ["..."],\n'
        '  "edge_cases": ["..."],\n'
        '  "test_gaps": ["..."],\n'
        '  "rollout_gaps": ["..."],\n'
        '  "findings": ["..."],\n'
        '  "simpler_alternative": "..." | "",\n'
        '  "confidence": "high" | "medium" | "low"\n'
        "}\n\n"
        "Task package:\n"
        f"{json.dumps(packet, indent=2, sort_keys=True)}"
    )


def run_task_shape_critique(
    task_id: str,
    project_id: str,
    *,
    agent_slug: str = _DEFAULT_AGENT,
) -> dict[str, Any]:
    """Request and persist an autonomous task-shape second opinion."""
    logger.info("Starting autonomous task-shape critique", task_id=task_id, project_id=project_id)

    task = task_store.get_task(task_id)
    if not task:
        return {"task_id": task_id, "status": "error", "message": "Task not found"}

    spirit = get_task_spirit(task_id)
    requirement = get_second_opinion_requirement(task, spirit)
    if not requirement.required:
        return {"task_id": task_id, "status": "skipped", "reason": "not_required"}

    subtasks = get_subtasks_for_task(task_id, include_steps=True)
    packet = _build_review_packet(task, spirit, subtasks)
    prompt = _build_request_message(packet)

    try:
        client = get_sync_client()
        response = client.complete(
            agent_slug=agent_slug,
            messages=[{"role": "user", "content": prompt}],
            project_id=project_id,
            external_id=task_id,
            purpose="task-second-opinion",
            use_memory=False,
            memory_group_id=None,
        )
        critique = parse_second_opinion_response(
            response.content,
            stage="task_shape",
            agent_slug=agent_slug,
        )
        persist_second_opinion(task_id, critique)
        sync_task_execution_readiness(task_id, approved_by="task-critique")
        log_task_event(
            task_id,
            f"Autonomous second opinion (task_shape) via {agent_slug}: {critique['verdict']} - {critique['summary']}",
        )
        return {
            "task_id": task_id,
            "status": "completed",
            "critique_status": critique["status"],
            "verdict": critique["verdict"],
            "summary": critique["summary"],
            "findings": critique["findings"],
        }
    except Exception as exc:
        logger.warning("Autonomous task-shape critique failed", task_id=task_id, error=str(exc))
        log_task_event(task_id, f"Autonomous task-shape critique failed: {exc}")
        return {"task_id": task_id, "status": "error", "message": str(exc)}
