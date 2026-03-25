"""Helpers for preserving rich task-plan metadata in task_spirit.context."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from .task_harness import normalize_execution_contract

_STRING_FIELDS = ("objective", "spirit_anti", "testing_strategy")
_LIST_FIELDS = (
    "constraints",
    "risks",
    "files_to_create",
    "files_to_modify",
    "references",
)
_CONTEXT_DERIVED_FIELDS = (
    "objective",
    "spirit_anti",
    "constraints",
    "decisions",
    "risks",
    "files_to_create",
    "files_to_modify",
    "references",
    "testing_strategy",
    "second_opinion",
    "execution_contract",
    "subtasks",
)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = _clean_text(item)
        if text:
            cleaned.append(text)
    return cleaned


def normalize_plan_steps(steps: Any) -> list[dict[str, Any]]:
    """Normalize planner steps into a stable JSON-friendly shape."""
    if not isinstance(steps, list):
        return []

    normalized: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        if isinstance(step, Mapping):
            step_data = cast(Mapping[str, Any], step)
            description = _clean_text(step_data.get("description"))
            if not description:
                continue
            raw_passes = step_data.get("passes")
            normalized_step: dict[str, Any] = {
                "step_number": int(step_data.get("step_number") or index),
                "description": description,
                "passes": bool(raw_passes),
            }
            spec = step_data.get("spec")
            if isinstance(spec, Mapping) and spec:
                normalized_step["spec"] = dict(spec)
            normalized.append(normalized_step)
            continue

        description = _clean_text(step)
        if description:
            normalized.append(
                {
                    "step_number": index,
                    "description": description,
                    "passes": False,
                }
            )

    return normalized


def normalize_plan_subtasks(subtasks: Any) -> list[dict[str, Any]]:
    """Normalize plan subtasks for round-trip storage in context."""
    if not isinstance(subtasks, list):
        return []

    normalized: list[dict[str, Any]] = []
    for index, subtask in enumerate(subtasks, start=1):
        if not isinstance(subtask, Mapping):
            continue
        subtask_data = cast(Mapping[str, Any], subtask)

        subtask_id = (
            _clean_text(subtask_data.get("subtask_id") or subtask_data.get("id")) or f"{index}.1"
        )
        description = _clean_text(subtask_data.get("description"))
        if not description:
            continue

        normalized_subtask: dict[str, Any] = {
            "subtask_id": subtask_id,
            "description": description,
        }
        if phase := _clean_text(subtask_data.get("phase")):
            normalized_subtask["phase"] = phase
        if subtask_type := _clean_text(subtask_data.get("subtask_type")):
            normalized_subtask["subtask_type"] = subtask_type
        if depends_on := _clean_string_list(subtask_data.get("depends_on")):
            normalized_subtask["depends_on"] = depends_on
        if steps := normalize_plan_steps(subtask_data.get("steps")):
            normalized_subtask["steps"] = steps
        normalized.append(normalized_subtask)

    return normalized


def build_task_plan_context(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Build the canonical round-trip context blob for task plans."""
    source = payload if isinstance(payload, dict) else {}
    raw_context = source.get("context")
    context: dict[str, Any] = dict(raw_context) if isinstance(raw_context, Mapping) else {}

    for field in _STRING_FIELDS:
        if value := _clean_text(source.get(field)):
            context[field] = value

    for field in _LIST_FIELDS:
        if values := _clean_string_list(source.get(field)):
            context[field] = values

    decisions = source.get("decisions")
    if isinstance(decisions, list) and decisions:
        context["decisions"] = decisions

    second_opinion = source.get("second_opinion")
    if second_opinion:
        context["second_opinion"] = second_opinion

    execution_contract = normalize_execution_contract(
        source.get("execution_contract") or context.get("execution_contract")
    )
    if execution_contract:
        context["execution_contract"] = execution_contract

    if subtasks := normalize_plan_subtasks(source.get("subtasks")):
        context["subtasks"] = subtasks

    return {key: value for key, value in context.items() if value not in (None, "", [], {})}


def hydrate_task_plan_fields(record: dict[str, Any] | None) -> dict[str, Any]:
    """Promote plan fields stored in context back onto the record for consumers."""
    hydrated = dict(record or {})
    context = hydrated.get("context")
    if not isinstance(context, dict):
        return hydrated

    for field in _CONTEXT_DERIVED_FIELDS:
        if hydrated.get(field) not in (None, "", [], {}):
            continue
        value = context.get(field)
        if value not in (None, "", [], {}):
            hydrated[field] = value

    return hydrated


def get_plan_subtask_map(context: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Return normalized plan subtask specs keyed by subtask_id."""
    if not isinstance(context, dict):
        return {}
    return {
        subtask["subtask_id"]: subtask
        for subtask in normalize_plan_subtasks(context.get("subtasks"))
        if subtask.get("subtask_id")
    }
