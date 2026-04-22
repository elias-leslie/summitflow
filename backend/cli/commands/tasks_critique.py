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
from app.storage import get_events_by_trace, log_task_event
from app.storage import tasks as task_store
from app.storage.subtasks import get_subtasks_for_task
from app.storage.task_spirit import get_task_spirit

from ..output import output_error, output_json

logger = get_logger(__name__)

_DEFAULT_AGENT = "specifier"
_VALID_STAGES = {"task_shape", "pre_close", "both"}
_CONTEXT_KEYS = (
    "files_to_modify",
    "files_to_create",
    "risks",
    "references",
    "testing_strategy",
    "execution_contract",
)
_STAGE_LENSES = {
    "task_shape": (
        "Judge whether implementation can start safely from this package. "
        "Focus on missing contract, hidden dependencies, ambiguous precedence, "
        "verification gaps, and simpler paths."
    ),
    "pre_close": (
        "Judge whether this task is truly ready to close. "
        "Focus on residual risk, incomplete verification, compatibility gaps, "
        "and unfinished operator-facing changes."
    ),
    "both": (
        "Judge both implementation readiness and closeout readiness. "
        "Only call out issues that materially affect one of those gates."
    ),
}


def _normalize_stage(stage: str) -> str:
    normalized = str(stage or "").strip().lower()
    if normalized not in _VALID_STAGES:
        raise ValueError(f"Unsupported critique stage: {stage}")
    return normalized


def _serialize_step(step: dict[str, Any], *, guidance_only: bool = False) -> dict[str, Any]:
    serialized = {
        "step_number": step.get("step_number"),
        "description": step.get("description"),
        "depends_on": step.get("depends_on") or [],
        "passes": None if guidance_only else step.get("passes"),
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
            for key in ("required", "stage", "status")
            if second_opinion.get(key) not in (None, "", [], {})
        }
    return serialized


def _parse_evidence_message(message: Any) -> dict[str, str] | None:
    if not isinstance(message, str):
        return None
    normalized_message = message.strip()
    if normalized_message.startswith("[") and "]" in normalized_message:
        _, _, remainder = normalized_message.partition("]")
        if remainder.lstrip().startswith("EVIDENCE:"):
            normalized_message = remainder.lstrip()
    if not normalized_message.startswith("EVIDENCE:"):
        return None
    fields: dict[str, str] = {}
    for index, segment in enumerate(normalized_message[len("EVIDENCE:") :].split("|")):
        key, sep, value = segment.partition(":")
        if not sep:
            if index == 0 and key.strip() and not fields.get("kind"):
                fields["kind"] = key.strip()
            continue
        normalized_key = key.strip().lower()
        normalized_value = value.strip()
        if not normalized_key or not normalized_value:
            continue
        fields[normalized_key] = normalized_value
    if not all(fields.get(key) for key in ("kind", "artifact", "state")):
        return None
    evidence = {
        "kind": fields["kind"],
        "artifact": fields["artifact"],
        "state": fields["state"],
    }
    if fields.get("notes"):
        evidence["notes"] = fields["notes"]
    return evidence


def _collect_closeout_evidence(task_id: str) -> list[dict[str, str]]:
    try:
        events = get_events_by_trace(task_id, visibility="user", limit=5000)
    except Exception as exc:  # pragma: no cover - defensive logging path
        logger.warning("Failed to load pre-close evidence", task_id=task_id, error=str(exc))
        return []
    return [
        parsed
        for event in events
        if (parsed := _parse_evidence_message(event.get("message"))) is not None
    ]


def _build_artifact_flags(evidence: list[dict[str, str]]) -> dict[str, bool]:
    kinds = {entry.get("kind") for entry in evidence}
    return {
        "opus_guidance_logged": "guidance" in kinds,
        "migration_decision_logged": "decision" in kinds,
    }


def _build_closeout_summary(
    task: dict[str, Any],
    serialized_subtasks: list[dict[str, Any]],
) -> dict[str, Any]:
    incomplete_subtasks = [
        str(subtask.get("subtask_id") or "")
        for subtask in serialized_subtasks
        if subtask.get("passes") is not True and subtask.get("subtask_id")
    ]
    evidence = _collect_closeout_evidence(str(task["id"]))
    return {
        "task_status": task.get("status"),
        "completion_ready": len(incomplete_subtasks) == 0,
        "subtasks_completed": sum(1 for subtask in serialized_subtasks if subtask.get("passes") is True),
        "subtasks_total": len(serialized_subtasks),
        "incomplete_subtasks": incomplete_subtasks,
        "evidence": evidence,
        "artifact_flags": _build_artifact_flags(evidence),
    }


def _serialize_subtask(st: dict[str, Any], *, stage: str = "task_shape") -> dict[str, Any]:
    normalized_stage = _normalize_stage(stage)
    include_closeout_fields = normalized_stage in {"pre_close", "both"}
    guidance_only = include_closeout_fields and st.get("steps_source") == "plan_context"
    serialized = {
        "subtask_id": st.get("subtask_id"),
        "phase": st.get("phase"),
        "subtask_type": st.get("subtask_type"),
        "status": st.get("status"),
        "passes": st.get("passes") if include_closeout_fields else None,
        "depends_on": st.get("depends_on") or [],
        "description": st.get("description"),
        "steps": [
            _serialize_step(step, guidance_only=guidance_only)
            for step in (st.get("steps_from_table") or st.get("steps") or [])
            if isinstance(step, dict)
            and any(
                step.get(key) not in (None, [], {})
                for key in ("description", "step_number", "depends_on", "passes", "spec")
            )
        ],
        "steps_guidance_only": True if guidance_only else None,
    }
    return {key: value for key, value in serialized.items() if value not in (None, [], {})}


def _build_review_packet(
    task: dict[str, Any],
    spirit: dict[str, Any] | None,
    subtasks: list[dict[str, Any]],
    *,
    stage: str = "task_shape",
) -> dict[str, Any]:
    """Build the compact task-shaping packet reviewed by Agent Hub."""
    normalized_stage = _normalize_stage(stage)
    serialized_subtasks = [_serialize_subtask(st, stage=normalized_stage) for st in subtasks]
    packet = {
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
        "subtasks": serialized_subtasks,
    }
    if normalized_stage in {"pre_close", "both"}:
        packet["closeout"] = _build_closeout_summary(task, serialized_subtasks)
    return packet


def _build_request_message(packet: dict[str, Any], *, stage: str) -> str:
    """Build the variable request message for the runtime critic prompt."""
    normalized_stage = _normalize_stage(stage)
    return (
        f"Stage: {normalized_stage}\n"
        f"Stage lens: {_STAGE_LENSES[normalized_stage]}\n"
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


def _call_agent(
    task: dict[str, Any],
    task_id: str,
    stage: str,
    agent_slug: str,
) -> dict[str, Any]:
    """Call the agent hub and return the parsed critique dict."""
    normalized_stage = _normalize_stage(stage)
    spirit = get_task_spirit(task_id)
    subtasks = get_subtasks_for_task(task_id, include_steps=True)
    packet = _build_review_packet(task, spirit, subtasks, stage=normalized_stage)
    prompt = _build_request_message(packet, stage=normalized_stage)

    client = get_sync_client()
    try:
        response = client.complete(
            agent_slug=agent_slug,
            messages=[{"role": "user", "content": prompt}],
            project_id=task["project_id"],
            external_id=task_id,
            purpose="task-second-opinion",
            use_memory=False,
            memory_group_id=None,
        )
        return parse_second_opinion_response(
            response.content, stage=normalized_stage, agent_slug=agent_slug
        )
    except Exception as exc:
        logger.exception("Task critique failed", task_id=task_id)
        output_error(f"Failed to obtain critique: {exc}")
        raise typer.Exit(1) from exc


def _persist_critique(
    task_id: str,
    stage: str,
    agent_slug: str,
    critique: dict[str, Any],
    requirement: Any,
) -> None:
    """Persist, sync readiness, log event, and emit JSON output."""
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


def critique_task_command(
    task_id: str,
    stage: str = "task_shape",
    agent_slug: str = _DEFAULT_AGENT,
    force: bool = False,
) -> None:
    """Request and persist a second-opinion critique for a task."""
    try:
        stage = _normalize_stage(stage)
    except ValueError as exc:
        output_error(str(exc))
        raise typer.Exit(1) from exc
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

    critique = _call_agent(task, task_id, stage, agent_slug)
    _persist_critique(task_id, stage, agent_slug, critique, requirement)
