"""Task critique command for second-opinion reviews."""

from __future__ import annotations

import json
from typing import Any

import typer

from app.logging_config import get_logger
from app.services.agent_hub_client import get_sync_client
from app.services.task_execution_readiness import sync_task_execution_readiness
from app.services.task_second_opinion import (
    get_second_opinion_requirement,
    parse_second_opinion_response,
    persist_second_opinion,
)
from app.storage import log_task_event
from app.storage import tasks as task_store
from app.storage.subtasks import get_subtasks_for_task
from app.storage.task_spirit import get_task_spirit

from ..output import output_error, output_json

logger = get_logger(__name__)

_DEFAULT_AGENT = "specifier"


def _build_review_packet(
    task: dict[str, Any],
    spirit: dict[str, Any] | None,
    subtasks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the compact task-shaping packet reviewed by Agent Hub."""
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
            "context": (spirit or {}).get("context") or task.get("context") or {},
        },
        "subtasks": [
            {
                "subtask_id": st.get("subtask_id"),
                "phase": st.get("phase"),
                "subtask_type": st.get("subtask_type"),
                "description": st.get("description"),
                "steps": [
                    step.get("description")
                    for step in (st.get("steps_from_table") or st.get("steps") or [])
                    if step.get("description")
                ],
            }
            for st in subtasks
        ],
    }


def _build_prompt(packet: dict[str, Any], *, stage: str) -> str:
    """Build a deterministic critique prompt."""
    return (
        "Review this task package as an independent second opinion.\n\n"
        f"Stage: {stage}\n"
        "Focus on missing requirements, weak assumptions, edge cases, test gaps, "
        "rollout/monitoring gaps, and simpler alternatives.\n\n"
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


def critique_task_command(
    task_id: str,
    stage: str = "task_shape",
    agent_slug: str = _DEFAULT_AGENT,
    force: bool = False,
) -> None:
    """Request and persist a second-opinion critique for a task."""
    task = task_store.get_task(task_id)
    if not task:
        output_error(f"Task not found: {task_id}")
        raise typer.Exit(1)

    spirit = get_task_spirit(task_id)
    requirement = get_second_opinion_requirement(task, spirit)
    if not requirement.required and not force:
        output_error(
            f"Task {task_id} does not currently require a second opinion. "
            "Use --force to record one anyway."
        )
        raise typer.Exit(1)

    subtasks = get_subtasks_for_task(task_id, include_steps=True)
    packet = _build_review_packet(task, spirit, subtasks)
    prompt = _build_prompt(packet, stage=stage)

    client = get_sync_client()
    try:
        response = client.complete(
            agent_slug=agent_slug,
            messages=[{"role": "user", "content": prompt}],
            project_id=task["project_id"],
            external_id=task_id,
            purpose="task-second-opinion",
            use_memory=True,
            memory_group_id=f"project:{task['project_id']}",
            tier_preference="advanced",
        )
        critique = parse_second_opinion_response(
            response.content, stage=stage, agent_slug=agent_slug
        )
    except Exception as exc:
        logger.exception("Task critique failed", task_id=task_id)
        output_error(f"Failed to obtain critique: {exc}")
        raise typer.Exit(1) from exc

    persist_second_opinion(task_id, critique)
    sync_task_execution_readiness(task_id, approved_by="task-critique")
    log_task_event(
        task_id,
        f"Second opinion ({stage}) via {agent_slug}: {critique['verdict']} - {critique['summary']}",
    )

    output_json(
        {
            "task_id": task_id,
            "stage": stage,
            "required": requirement.required,
            "requirement_reasons": requirement.reasons,
            "status": critique["status"],
            "verdict": critique["verdict"],
            "summary": critique["summary"],
            "findings": critique["findings"],
            "missing_requirements": critique["missing_requirements"],
            "edge_cases": critique["edge_cases"],
            "test_gaps": critique["test_gaps"],
            "rollout_gaps": critique["rollout_gaps"],
            "simpler_alternative": critique["simpler_alternative"],
            "confidence": critique["confidence"],
            "agent_slug": agent_slug,
        }
    )

