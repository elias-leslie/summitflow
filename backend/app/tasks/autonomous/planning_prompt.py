"""Prompt construction for autonomous planning."""

from __future__ import annotations

import json
from typing import Any

from ...services.context_gatherer import PRECISION_CODE_SEARCH_GUIDANCE
from ...services.task_plan_context import extract_task_plan_fields
from ...services.task_second_opinion import get_second_opinion_entry
from ...storage.task_spirit import get_task_spirit
from .exec_modules._routing_maps import SUBTASK_TYPE_AGENT_MAP

SUBTASK_TYPE_PROMPT = "|".join(SUBTASK_TYPE_AGENT_MAP)

_PLAN_FEEDBACK_KEYS = (
    "objective",
    "spirit_anti",
    "constraints",
    "decisions",
    "risks",
    "files_to_create",
    "files_to_modify",
    "references",
    "testing_strategy",
)
_SECOND_OPINION_KEYS = (
    "required",
    "stage",
    "status",
    "summary",
    "findings",
    "missing_requirements",
    "edge_cases",
    "test_gaps",
    "rollout_gaps",
    "simpler_alternative",
)
_SUBSTANTIVE_SECOND_OPINION_KEYS = frozenset(
    {
        "summary",
        "findings",
        "missing_requirements",
        "edge_cases",
        "test_gaps",
        "rollout_gaps",
        "simpler_alternative",
    }
)


def planning_feedback_payload(task_id: str) -> dict[str, Any]:
    spirit = get_task_spirit(task_id) or {}
    payload = _plan_context_payload(spirit)
    if second_opinion := _second_opinion_payload(spirit):
        payload["second_opinion"] = second_opinion
    return payload


def _plan_context_payload(spirit: dict[str, Any]) -> dict[str, Any]:
    plan_fields = extract_task_plan_fields(
        {
            "done_when": spirit.get("done_when"),
            "context": spirit.get("context"),
        }
    )
    return {
        key: value
        for key in _PLAN_FEEDBACK_KEYS
        if (value := plan_fields.get(key)) not in (None, "", [], {})
    }


def _second_opinion_payload(spirit: dict[str, Any]) -> dict[str, Any]:
    second_opinion = get_second_opinion_entry(spirit)
    if not isinstance(second_opinion, dict) or not second_opinion:
        return {}
    filtered = {
        key: second_opinion.get(key)
        for key in _SECOND_OPINION_KEYS
        if second_opinion.get(key) not in (None, "", [], {})
    }
    if not any(key in filtered for key in _SUBSTANTIVE_SECOND_OPINION_KEYS):
        return {}
    return filtered


def build_planning_prompt(
    title: str,
    description: str,
    precision_context: str = "",
    planning_feedback: dict[str, Any] | None = None,
) -> str:
    """Build the prompt for the planner agent."""
    return (
        "Create an implementation plan for this task.\n\n"
        f"Title: {title}\n"
        f"Description: {description or '(no description)'}\n"
        f"{_precision_block(precision_context)}{_feedback_block(planning_feedback or {})}"
        "Build a plan that is execution-ready for an autonomous coding agent.\n"
        "- Keep scope tight and explicit.\n"
        "- For any existing file you expect to touch, include it in context.files_to_modify when you can infer it.\n"
        "- If touched files already contain local duplication, dead code, stale shims, or obvious structural mess, absorb that cleanup into this task instead of deferring it, unless doing so would clearly broaden scope or risk behavior changes.\n"
        "- If cleanup must be deferred, say why in constraints.\n"
        "- Use step.spec.verify_commands when a step has concrete verification the agent should run.\n\n"
        "You MUST respond with a JSON object (no markdown, no explanation outside the JSON):\n"
        f"{_PLAN_SCHEMA}"
    )


def _precision_block(precision_context: str) -> str:
    if not precision_context:
        return ""
    return f"\n## Precision Code Search\n\n{precision_context}\n\n{PRECISION_CODE_SEARCH_GUIDANCE}\n"


def _feedback_block(feedback_payload: dict[str, Any]) -> str:
    if not feedback_payload:
        return ""
    return (
        "\n## Existing task-plan context and review feedback\n\n"
        f"{json.dumps(feedback_payload, indent=2, sort_keys=True)}\n\n"
        "Treat second_opinion findings as advisory input, not a blocking contract.\n"
        "Use concrete critique points when valid; do not loop solely on NEEDS_REVISION or pending status.\n"
        "Address concrete missing requirements or edge cases in the revised plan.\n"
    )


_PLAN_SCHEMA = """{
    "objective": "Clear 1-2 sentence objective",
    "spirit_anti": "What must NOT happen while implementing this task",
    "done_when": [
        "Concrete completion criterion",
        "Another concrete completion criterion"
    ],
    "decisions": [
        {
            "id": "d1",
            "title": "Important implementation choice",
            "outcome": "Chosen approach",
            "rationale": "Why this is the right tradeoff"
        }
    ],
    "subtasks": [
        {
            "subtask_id": "1.1",
            "phase": "implementation",
            "subtask_type": "__SUBTASK_TYPES__",
            "description": "What this subtask accomplishes",
            "steps": [
                {
                    "description": "Specific implementation step",
                    "spec": {
                        "verify_commands": ["Optional command to verify this step"]
                    }
                }
            ],
            "depends_on": []
        }
    ],
    "constraints": ["Any constraints or non-goals"],
    "context": {
        "files_to_modify": ["existing/file.py"],
        "files_to_create": ["new/file.ts"],
        "risks": ["Known risk or gotcha"]
    }
}""".replace("__SUBTASK_TYPES__", SUBTASK_TYPE_PROMPT)
