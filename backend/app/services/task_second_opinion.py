"""Second-opinion policy and persistence helpers for task execution."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..storage.task_spirit import get_task_spirit, update_task_spirit, upsert_task_spirit

_HIGH_RISK_LABEL_TOKENS = {
    "auth",
    "billing",
    "core",
    "critical",
    "database",
    "db",
    "infra",
    "migration",
    "observability",
    "queue",
    "security",
    "worker",
}
_COMPLETED_STATUSES = {"completed", "waived"}
_SECOND_OPINION_CONTEXT_KEY = "second_opinion"


@dataclass
class SecondOpinionRequirement:
    """Requirement status for task-shape second-opinion review."""

    required: bool
    reasons: list[str]
    recommended_stage: str = "task_shape"


def _normalize_labels(task: dict[str, Any]) -> set[str]:
    labels = task.get("labels") or []
    normalized: set[str] = set()
    for label in labels:
        text = str(label).strip().lower()
        if not text:
            continue
        normalized.add(text)
        normalized.update(part for part in re.split(r"[^a-z0-9]+", text) if part)
    return normalized


def get_second_opinion_requirement(
    task: dict[str, Any],
    spirit: dict[str, Any] | None = None,
) -> SecondOpinionRequirement:
    """Return whether the task should require a second-opinion review."""
    spirit = spirit or {}
    reasons: list[str] = []
    complexity = str(task.get("complexity") or spirit.get("complexity") or "SIMPLE")
    priority = int(task.get("priority") or 2)
    labels = _normalize_labels(task)

    if complexity == "COMPLEX":
        reasons.append("complexity=COMPLEX")
    if priority <= 1:
        reasons.append(f"priority=P{priority}")

    matching_labels = sorted(labels & _HIGH_RISK_LABEL_TOKENS)
    if matching_labels:
        reasons.append("high-risk labels: " + ", ".join(matching_labels))

    return SecondOpinionRequirement(required=bool(reasons), reasons=reasons)


def get_second_opinion_entry(spirit: dict[str, Any] | None) -> dict[str, Any]:
    """Extract second-opinion context from task spirit."""
    if not spirit:
        return {}
    context = spirit.get("context") or {}
    if not isinstance(context, dict):
        return {}
    entry = context.get(_SECOND_OPINION_CONTEXT_KEY)
    return entry if isinstance(entry, dict) else {}


def merge_second_opinion_into_context(
    context: dict[str, Any] | None,
    second_opinion: dict[str, Any],
) -> dict[str, Any]:
    """Merge a second-opinion payload into an existing spirit context blob."""
    merged = dict(context or {})
    merged[_SECOND_OPINION_CONTEXT_KEY] = second_opinion
    return merged


def build_second_opinion_entry(
    task: dict[str, Any],
    spirit: dict[str, Any] | None = None,
    *,
    source: str = "system",
) -> dict[str, Any] | None:
    """Return the desired second-opinion context entry for this task, if required."""
    spirit = spirit or {}
    requirement = get_second_opinion_requirement(task, spirit)
    if not requirement.required:
        return None

    existing = get_second_opinion_entry(spirit)
    entry = dict(existing)
    entry["required"] = True
    entry["stage"] = str(entry.get("stage") or requirement.recommended_stage)
    entry["status"] = str(entry.get("status") or "pending")
    entry["reasons"] = requirement.reasons
    entry.setdefault("requested_by", source)
    entry.setdefault("requested_at", datetime.now(UTC).isoformat())
    return entry


def ensure_second_opinion_tracking(
    task_id: str,
    task: dict[str, Any],
    spirit: dict[str, Any] | None = None,
    *,
    source: str = "system",
) -> dict[str, Any] | None:
    """Persist pending second-opinion tracking for qualifying tasks when absent."""
    spirit = spirit if spirit is not None else get_task_spirit(task_id)
    entry = build_second_opinion_entry(task, spirit, source=source)
    if entry is None:
        return None

    existing = get_second_opinion_entry(spirit)
    if existing == entry:
        return entry

    context = merge_second_opinion_into_context((spirit or {}).get("context"), entry)
    if spirit:
        updated = update_task_spirit(task_id, context=context)
        if updated is not None:
            return entry
        raise ValueError(f"Failed to update task_spirit for {task_id}")

    upsert_task_spirit(task_id=task_id, context={_SECOND_OPINION_CONTEXT_KEY: entry})
    return entry


def assess_second_opinion_readiness(
    task: dict[str, Any],
    spirit: dict[str, Any] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """Return (issues, suggestions, missing_fields) for second-opinion readiness."""
    spirit = spirit or {}
    requirement = get_second_opinion_requirement(task, spirit)
    if not requirement.required:
        return [], [], []

    entry = get_second_opinion_entry(spirit)
    status = str(entry.get("status") or "").lower()
    stage = str(entry.get("stage") or requirement.recommended_stage)
    summary = str(entry.get("summary") or "").strip()

    if status in _COMPLETED_STATUSES and stage in {"task_shape", "both"} and summary:
        return [], [], []

    issues = [
        "Missing completed task-shape second opinion for high-risk task "
        f"({'; '.join(requirement.reasons)})"
    ]
    suggestions = [
        "Run `st critique <task-id>` to record a task-shape critique before autonomous execution"
    ]
    missing_fields = ["second_opinion"]
    if entry and status in (_COMPLETED_STATUSES | {"needs_revision"}) and not summary:
        issues.append("Second-opinion entry is present but missing a summary")
    elif entry and stage not in {"task_shape", "both"}:
        issues.append(f"Second-opinion stage must include task_shape (found: {stage})")
    return issues, suggestions, missing_fields


def _parse_json_object(content: str) -> dict[str, Any]:
    match = re.search(r"\{[\s\S]*\}", content)
    if not match:
        raise ValueError("Response did not contain a JSON object")
    return json.loads(match.group(0))


def _normalize_text_list(items: Any) -> list[str]:
    """Normalize string-or-object lists from agent responses into plain text lines."""
    normalized: list[str] = []
    for item in items or []:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            issue = str(item.get("issue") or item.get("summary") or "").strip()
            why = str(item.get("why_it_matters") or item.get("impact") or "").strip()
            text = f"{issue} — {why}".strip(" —")
        else:
            text = str(item).strip()
        if text:
            normalized.append(text)
    return normalized


def parse_second_opinion_response(content: str, *, stage: str, agent_slug: str) -> dict[str, Any]:
    """Parse a task-critic response into persisted context shape."""
    parsed = _parse_json_object(content)
    verdict = str(parsed.get("verdict") or "NEEDS_REVISION").upper()
    findings = _normalize_text_list(parsed.get("findings"))
    test_gaps = _normalize_text_list(parsed.get("test_gaps"))
    rollout_gaps = _normalize_text_list(parsed.get("rollout_gaps"))
    missing = _normalize_text_list(parsed.get("missing_requirements"))
    edge_cases = _normalize_text_list(parsed.get("edge_cases"))

    summary = str(parsed.get("summary") or "").strip()
    if not summary:
        raise ValueError("Critique response missing summary")

    status = "completed" if verdict == "APPROVED" else "needs_revision"
    return {
        "required": True,
        "stage": stage,
        "status": status,
        "verdict": verdict,
        "summary": summary,
        "findings": findings,
        "missing_requirements": missing,
        "edge_cases": edge_cases,
        "test_gaps": test_gaps,
        "rollout_gaps": rollout_gaps,
        "simpler_alternative": str(parsed.get("simpler_alternative") or "").strip() or None,
        "confidence": str(parsed.get("confidence") or "").strip() or None,
        "reviewed_by_agent": agent_slug,
        "reviewed_at": datetime.now(UTC).isoformat(),
    }


def persist_second_opinion(
    task_id: str,
    second_opinion: dict[str, Any],
) -> dict[str, Any]:
    """Store a second-opinion payload under task_spirit.context.second_opinion."""
    spirit = get_task_spirit(task_id)
    if spirit:
        context = merge_second_opinion_into_context(spirit.get("context"), second_opinion)
        updated = update_task_spirit(task_id, context=context)
        if updated is not None:
            return updated
        raise ValueError(f"Failed to update task_spirit for {task_id}")

    return upsert_task_spirit(task_id=task_id, context={_SECOND_OPINION_CONTEXT_KEY: second_opinion})
