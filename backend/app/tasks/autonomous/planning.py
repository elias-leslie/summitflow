"""Autonomous planning task using Agent Hub run_agent().

Creates implementation plans by running the planner agent in the project directory.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...services.context_gatherer import (
    PRECISION_CODE_SEARCH_GUIDANCE,
    collect_precision_code_search_context,
)
from ...services.task_harness import apply_execution_contract_defaults
from ...services.task_plan_context import extract_task_plan_fields
from ...services.task_second_opinion import get_second_opinion_entry
from ...storage import log_task_event
from ...storage import tasks as task_store
from ...storage.task_spirit import get_task_spirit
from .planning_routing import route_based_on_complexity, supervisor_validate_plan
from .planning_storage import save_plan_to_database

logger = get_logger(__name__)


def _planning_feedback_payload(task_id: str) -> dict[str, Any]:
    spirit = get_task_spirit(task_id) or {}
    payload: dict[str, Any] = {}

    plan_fields = extract_task_plan_fields(
        {
            "done_when": spirit.get("done_when"),
            "context": spirit.get("context"),
        }
    )
    for key in ("objective", "spirit_anti", "constraints", "decisions", "risks", "files_to_create", "files_to_modify", "references", "testing_strategy"):
        value = plan_fields.get(key)
        if value not in (None, "", [], {}):
            payload[key] = value

    second_opinion = get_second_opinion_entry(spirit)
    if isinstance(second_opinion, dict) and second_opinion:
        filtered_second_opinion = {
            key: second_opinion.get(key)
            for key in (
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
            if second_opinion.get(key) not in (None, "", [], {})
        }
        if filtered_second_opinion:
            payload["second_opinion"] = filtered_second_opinion

    return payload


def _build_planning_prompt(
    title: str,
    description: str,
    precision_context: str = "",
    planning_feedback: dict[str, Any] | None = None,
) -> str:
    """Build the prompt for the planner agent.

    Args:
        title: Task title
        description: Task description

    Returns:
        Formatted prompt string
    """
    precision_block = (
        f"\n## Precision Code Search\n\n{precision_context}\n\n{PRECISION_CODE_SEARCH_GUIDANCE}\n"
        if precision_context
        else ""
    )
    feedback_payload = planning_feedback or {}
    feedback_block = ""
    if feedback_payload:
        feedback_block = (
            "\n## Existing task-plan context and review feedback\n\n"
            f"{json.dumps(feedback_payload, indent=2, sort_keys=True)}\n\n"
            "Treat second_opinion findings as advisory input, not a blocking contract.\n"
            "Use concrete critique points when valid; do not loop solely on NEEDS_REVISION or pending status.\n"
        )
    return f"""Create an implementation plan for this task.

Title: {title}
Description: {description or "(no description)"}
{precision_block}{feedback_block}
Build a plan that is execution-ready for an autonomous coding agent.
- Keep scope tight and explicit.
- For any existing file you expect to touch, include it in context.files_to_modify when you can infer it.
- If touched files already contain local duplication, dead code, stale shims, or obvious structural mess, absorb that cleanup into this task instead of deferring it, unless doing so would clearly broaden scope or risk behavior changes.
- If cleanup must be deferred, say why in constraints.
- Use step.spec.verify_commands when a step has concrete verification the agent should run.

You MUST respond with a JSON object (no markdown, no explanation outside the JSON):
{{
    "objective": "Clear 1-2 sentence objective",
    "spirit_anti": "What must NOT happen while implementing this task",
    "done_when": [
        "Concrete completion criterion",
        "Another concrete completion criterion"
    ],
    "decisions": [
        {{
            "id": "d1",
            "title": "Important implementation choice",
            "outcome": "Chosen approach",
            "rationale": "Why this is the right tradeoff"
        }}
    ],
    "subtasks": [
        {{
            "subtask_id": "1.1",
            "phase": "implementation",
            "subtask_type": "backend|frontend|ui-design|refactor|bug-fix|test|config",
            "description": "What this subtask accomplishes",
            "steps": [
                {{
                    "description": "Specific implementation step",
                    "spec": {{
                        "verify_commands": ["Optional command to verify this step"]
                    }}
                }}
            ],
            "depends_on": []
        }}
    ],
    "constraints": ["Any constraints or non-goals"],
    "execution_contract": {{
        "mode": "code_only|runtime_eval|runtime_eval_plus_design",
        "target_urls": ["/app/example"],
        "user_flows": [
            {{
                "title": "Key user journey",
                "setup": ["Optional setup step"],
                "actions": ["Navigate to the page"],
                "expected_outcomes": ["Visible runtime outcome"]
            }}
        ],
        "api_checks": [
            {{
                "method": "GET",
                "path": "/api/example",
                "status": 200,
                "body_expectations": ["Optional response marker"]
            }}
        ],
        "negative_cases": [
            {{
                "title": "Invalid request handling",
                "path": "/api/example/invalid",
                "status": 404
            }}
        ],
        "evidence_requirements": ["screenshot", "API response", "file:line citation"],
        "design_criteria": {{"rubric": ["originality", "visual cohesion", "craft", "usability"]}},
        "risk_notes": ["Compact evaluator focus areas"]
    }},
    "context": {{
        "files_to_modify": ["existing/file.py"],
        "files_to_create": ["new/file.ts"],
        "risks": ["Known risk or gotcha"]
    }}
}}"""


def _fetch_task_for_planning(task_id: str) -> dict[str, Any] | None:
    """Fetch the task and log a warning if not found.

    Args:
        task_id: The task ID to fetch

    Returns:
        Task dict, or None if not found
    """
    task = task_store.get_task(task_id)
    if not task:
        logger.warning("Task not found for planning", task_id=task_id)
    return task


def _process_plan_result(
    task_id: str, project_id: str, title: str, description: str, plan_data: dict[str, Any]
) -> dict[str, Any]:
    """Validate the parsed plan, persist it, and route by complexity.

    Args:
        task_id: The task ID
        project_id: The project ID (unused here but kept for future use)
        title: Task title
        description: Task description
        plan_data: Parsed plan dict from the planner agent

    Returns:
        Result dict with status and subtasks_created count
    """
    subtask_count = len(plan_data.get("subtasks", []))
    if subtask_count == 0:
        logger.warning("Planner produced 0 subtasks", task_id=task_id)
        task_store.update_task_status(task_id, "failed")
        log_task_event(task_id, "Planning failed: planner produced no subtasks")
        return {
            "task_id": task_id,
            "status": "error",
            "message": "Planner produced no subtasks",
        }

    save_plan_to_database(task_id, plan_data)
    route_based_on_complexity(task_id, title, description)

    return {
        "task_id": task_id,
        "status": "completed",
        "subtasks_created": subtask_count,
    }


def create_plan(task_id: str, project_id: str) -> dict[str, Any]:
    """Create an implementation plan using the planner agent.

    Uses Agent Hub run_agent() with the planner agent to:
    1. Analyze the task requirements
    2. Create subtasks with steps
    3. Route based on complexity

    Args:
        task_id: The task ID to plan
        project_id: The project ID

    Returns:
        Planning result with subtasks created
    """
    logger.info("Starting autonomous planning", task_id=task_id, project_id=project_id)

    task = _fetch_task_for_planning(task_id)
    if not task:
        return {"task_id": task_id, "status": "error", "message": "Task not found"}

    title = task.get("title", "")
    description = task.get("description", "")
    precision_context = collect_precision_code_search_context(
        project_id,
        [title, description],
        budget_tokens=1200,
    ).prompt_context
    planning_feedback = _planning_feedback_payload(task_id)
    prompt = _build_planning_prompt(title, description, precision_context, planning_feedback)

    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            project_id=project_id,
            agent_slug="planner",
        )

        plan_data = apply_execution_contract_defaults(task, _parse_plan_response(response.content))
        return _process_plan_result(task_id, project_id, title, description, plan_data)

    except Exception as e:
        logger.warning("Planning failed", task_id=task_id, error=str(e))
        task_store.update_task_status(task_id, "failed")
        log_task_event(task_id, f"Planning failed: {e}")
        return {"task_id": task_id, "status": "error", "message": str(e)}


def _parse_plan_response(content: str) -> dict[str, Any]:
    """Parse the planner agent's response into structured plan data.

    Args:
        content: Raw agent response content

    Returns:
        Parsed plan data with objective, subtasks, and constraints
    """
    try:
        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            parsed: dict[str, Any] = json.loads(json_match.group())
            return parsed
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse plan JSON", error=str(e))

    return {"objective": "Could not parse plan", "subtasks": [], "constraints": []}


# Re-export internal functions for backward compatibility with tests
_supervisor_validate_plan = supervisor_validate_plan
_save_plan_to_database = save_plan_to_database
_route_based_on_complexity = route_based_on_complexity
