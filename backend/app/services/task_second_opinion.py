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
_SECOND_OPINION_REVIEWS_KEY = "reviews"
_VALID_REVIEW_STAGES = {"task_shape", "pre_close", "both"}
_REVIEW_DETAIL_KEYS = {
    "summary",
    "verdict",
    "findings",
    "missing_requirements",
    "edge_cases",
    "test_gaps",
    "rollout_gaps",
    "simpler_alternative",
    "confidence",
    "reviewed_by_agent",
    "reviewed_at",
}


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


def _review_snapshot(review: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(review).items()
        if key != _SECOND_OPINION_REVIEWS_KEY
    }


def _review_history(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    history: dict[str, dict[str, Any]] = {}
    raw_history = entry.get(_SECOND_OPINION_REVIEWS_KEY)
    if isinstance(raw_history, dict):
        for stage, review in raw_history.items():
            if stage in _VALID_REVIEW_STAGES and isinstance(review, dict):
                history[stage] = _review_snapshot(review)

    stage = str(entry.get("stage") or "").strip().lower()
    if stage in _VALID_REVIEW_STAGES and stage not in history:
        history[stage] = _review_snapshot(entry)
    return history


def _task_shape_review(entry: dict[str, Any]) -> dict[str, Any]:
    history = _review_history(entry)
    for stage in ("task_shape", "both"):
        review = history.get(stage)
        if review:
            return review
    return {}


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


def reset_second_opinion_for_replan(
    task_id: str,
    *,
    source: str = "planning",
) -> dict[str, Any] | None:
    """Reset task-shape review status to pending after the plan package changes."""
    spirit = get_task_spirit(task_id)
    existing = get_second_opinion_entry(spirit)
    if not existing:
        return None

    current_review = _task_shape_review(existing) or (
        _review_snapshot(existing) if isinstance(existing, dict) else {}
    )
    status = str(current_review.get("status") or existing.get("status") or "").strip().lower()
    if status not in _COMPLETED_STATUSES | {"needs_revision"}:
        return existing

    pending_review = {
        "required": True,
        "stage": "task_shape",
        "status": "pending",
        "reasons": list(existing.get("reasons") or []),
        "requested_by": source,
        "requested_at": datetime.now(UTC).isoformat(),
    }
    history = _review_history(existing)
    history["task_shape"] = pending_review

    merged_primary = {
        key: value
        for key, value in dict(existing).items()
        if key not in _REVIEW_DETAIL_KEYS and key != _SECOND_OPINION_REVIEWS_KEY
    }
    merged_primary.update(pending_review)
    merged_primary[_SECOND_OPINION_REVIEWS_KEY] = history

    context = merge_second_opinion_into_context((spirit or {}).get("context"), merged_primary)
    updated = update_task_spirit(task_id, context=context)
    if updated is not None:
        return updated
    raise ValueError(f"Failed to update task_spirit for {task_id}")


def assess_second_opinion_readiness(
    task: dict[str, Any],
    spirit: dict[str, Any] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """Return advisory task-shape critique guidance.

    Task-shape critique findings are useful planning input, not an execution
    gate. Hard readiness stays with description, done_when, scope context,
    subtasks, and execution_contract.
    """
    spirit = spirit or {}
    requirement = get_second_opinion_requirement(task, spirit)
    if not requirement.required:
        return [], [], []

    entry = get_second_opinion_entry(spirit)
    review = _task_shape_review(entry) or (
        _review_snapshot(entry) if isinstance(entry, dict) else {}
    )
    status = str(review.get("status") or "").lower()
    stage = str(review.get("stage") or requirement.recommended_stage)
    summary = str(review.get("summary") or "").strip()

    if status in _COMPLETED_STATUSES and stage in {"task_shape", "both"} and summary:
        return [], [], []

    suggestions = []
    if status == "needs_revision" and summary:
        suggestions.append(
            "Review advisory task-shape critique findings when they are concrete"
        )
    elif status in {"pending", ""}:
        suggestions.append(
            "Optionally run `st critique <task-id>` for advisory task-shape review"
        )
    elif review and stage not in {"task_shape", "both"}:
        suggestions.append(
            f"Task-shape critique is advisory; current review stage is {stage}"
        )
    elif review and status in (_COMPLETED_STATUSES | {"needs_revision"}) and not summary:
        suggestions.append("Task-shape critique entry lacks advisory summary")
    else:
        suggestions.append(
            "Optionally use task-shape critique as advisory review input"
        )
    return [], suggestions, []


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
    incoming = _review_snapshot(second_opinion)
    incoming_stage = str(incoming.get("stage") or "").strip().lower()
    existing_entry = get_second_opinion_entry(spirit)
    existing_primary = _review_snapshot(existing_entry) if existing_entry else {}
    history = _review_history(existing_entry)
    if incoming_stage in _VALID_REVIEW_STAGES:
        history[incoming_stage] = incoming

    if incoming_stage in {"task_shape", "both"} or not _task_shape_review(existing_entry):
        merged_primary = {**existing_primary, **incoming}
    else:
        merged_primary = {**existing_primary, **_task_shape_review(existing_entry)}
    if history:
        merged_primary[_SECOND_OPINION_REVIEWS_KEY] = history

    if spirit:
        context = merge_second_opinion_into_context(spirit.get("context"), merged_primary)
        updated = update_task_spirit(task_id, context=context)
        if updated is not None:
            return updated
        raise ValueError(f"Failed to update task_spirit for {task_id}")

    return upsert_task_spirit(task_id=task_id, context={_SECOND_OPINION_CONTEXT_KEY: merged_primary})
