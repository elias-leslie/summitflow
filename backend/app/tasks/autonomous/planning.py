"""Autonomous planning task using Agent Hub run_agent().

Creates implementation plans by running the planner agent in the project directory.
"""

from __future__ import annotations

import json
from typing import Any

from celery import Task, shared_task

from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...services.complexity_assessor import ComplexityAssessor, ComplexityTier
from ...storage import log_task_event
from ...storage import tasks as task_store
from ...storage.subtasks import bulk_create_subtasks
from ...storage.task_spirit import create_task_spirit, get_task_spirit

logger = get_logger(__name__)


@shared_task(
    bind=True,
    name="autonomous.create_plan",
    acks_late=True,
    time_limit=600,  # 10 minutes hard limit
    soft_time_limit=540,  # 9 minutes soft limit
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=120,  # Max 2 minutes between retries
    max_retries=3,
)
def create_plan(self: Task[..., dict[str, Any]], task_id: str, project_id: str) -> dict[str, Any]:
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

    task = task_store.get_task(task_id)
    if not task:
        logger.warning("Task not found for planning", task_id=task_id)
        return {"task_id": task_id, "status": "error", "message": "Task not found"}

    title = task.get("title", "")
    description = task.get("description", "")

    prompt = f"""Create an implementation plan for this task:

Title: {title}
Description: {description or "(no description)"}

## Verification Requirements

For each step, provide verify_command and expected_output:

1. verify_command must:
   - Return exit 0 when step is complete
   - Use rg (ripgrep) for code searches, NOT grep
   - Escape special chars: parens \\( \\), brackets \\[ \\]
   - Use relative paths from project root (backend/, not /home/.../backend/)
   - Include actual code patterns (function names, class names, type annotations)

2. expected_output must:
   - Be a specific string that appears in output
   - NOT be generic like "success" or "found"

## Common verify_command patterns:

Code exists:
  verify_command: "rg -q 'def my_function\\(' backend/app/module.py && echo 'Found'"
  expected_output: "Found"

Type annotation:
  verify_command: "rg 'CONSTANT: int = ' backend/app/constants.py"
  expected_output: "CONSTANT: int = "

Import exists:
  verify_command: "rg '^from.*import.*MyClass' backend/app/module.py && echo 'Import found'"
  expected_output: "Import found"

Tests pass:
  verify_command: "cd backend && .venv/bin/pytest tests/test_module.py -q"
  expected_output: "passed"

## BAD verify_commands (DO NOT USE):
- "cat file | grep something"  # Use rg instead
- "ls /home/user/project/..."  # Absolute paths
- "/path/to/.venv/bin/pytest"  # Absolute venv path
- "grep 'pattern' file"        # Use rg

## Deploy steps (REQUIRED for backend/frontend phases):

Backend:
  verify_command: "./scripts/rebuild.sh --backend 2>&1 | rg -q 'Rebuild complete' && echo 'Rebuild complete'"
  expected_output: "Rebuild complete"

Frontend:
  verify_command: "./scripts/rebuild.sh --frontend 2>&1 | rg -q 'Rebuild complete' && echo 'Rebuild complete'"
  expected_output: "Rebuild complete"

## Runtime verification (REQUIRED - actually run the code):

IMPORTANT: Static checks (rg patterns) verify code EXISTS but not that it WORKS.
Each subtask MUST include at least one step that RUNS the changed code.

CLI changes (cli/*.py):
  verify_command: "cd backend && .venv/bin/python -c 'from cli.module import function; function(test_arg)'"
  expected_output: exit code 0

Or run the actual CLI:
  verify_command: "st <command> --compact 2>&1 | head -1"
  expected_output: (expected output prefix)

API endpoint changes:
  verify_command: "curl -s http://localhost:8001/api/endpoint | jq -r '.status // .error'"
  expected_output: "ok"

Library/module changes:
  verify_command: "cd backend && .venv/bin/python -c 'from app.module import MyClass; print(MyClass().method())'"
  expected_output: (expected output)

Formatter/output functions:
  verify_command: "cd backend && .venv/bin/python -c 'from cli.output import output_func; output_func({{}})'"
  expected_output: exit code 0

The runtime verification step catches bugs that pass static analysis but fail at runtime
(like calling fmt._truncate instead of fmt.truncate).

Output as JSON with this structure:
{{
    "objective": "...",
    "subtasks": [
        {{
            "subtask_id": "1.1",
            "phase": "backend|frontend|research|testing",
            "description": "...",
            "steps": [
                {{
                    "description": "...",
                    "verify_command": "command to verify (use rg, relative paths)",
                    "expected_output": "specific expected string"
                }}
            ]
        }}
    ],
    "constraints": ["..."]
}}"""

    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            project_id=project_id,
            agent_slug="planner",
        )

        plan_data = _parse_plan_response(response.content)
        _save_plan_to_database(task_id, plan_data)
        _route_based_on_complexity(task_id, title, description)

        return {
            "task_id": task_id,
            "status": "completed",
            "subtasks_created": len(plan_data.get("subtasks", [])),
        }

    except Exception as e:
        logger.warning("Planning failed", task_id=task_id, error=str(e))
        task_store.update_task_status(task_id, "blocked")
        log_task_event(task_id, f"Planning failed: {e}")
        return {"task_id": task_id, "status": "error", "message": str(e)}


def _parse_plan_response(content: str) -> dict[str, Any]:
    """Parse the planner agent's response into structured plan data."""
    import re

    try:
        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            parsed: dict[str, Any] = json.loads(json_match.group())
            _validate_and_fix_plan(parsed)
            return parsed
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse plan JSON", error=str(e))

    return {"objective": "Could not parse plan", "subtasks": [], "constraints": []}


def _validate_and_fix_plan(plan: dict[str, Any]) -> None:
    """Validate and fix common issues in verify_commands."""
    import re

    generic_outputs = {"success", "found", "ok", "done", "pass", "passed", "true", "yes"}

    for subtask in plan.get("subtasks", []):
        for step in subtask.get("steps", []):
            verify = step.get("verify_command", "")
            expected = step.get("expected_output", "")

            if verify:
                if "/home/" in verify:
                    logger.warning(
                        "Absolute path in verify_command",
                        subtask=subtask.get("subtask_id"),
                        verify=verify[:100],
                    )
                    step["verify_command"] = re.sub(r"/home/\w+/\w+/", "", verify)

                if "cat " in verify and "| grep" in verify:
                    logger.warning(
                        "cat|grep pattern in verify_command",
                        subtask=subtask.get("subtask_id"),
                    )
                    step["verify_command"] = re.sub(
                        r"cat\s+(\S+)\s*\|\s*grep\s+(.+)",
                        r"rg \2 \1",
                        verify,
                    )

                if verify.startswith("grep "):
                    step["verify_command"] = "rg " + verify[5:]

            if expected and expected.lower().strip() in generic_outputs:
                logger.warning(
                    "Generic expected_output",
                    subtask=subtask.get("subtask_id"),
                    expected=expected,
                )


def _save_plan_to_database(task_id: str, plan_data: dict[str, Any]) -> None:
    """Save parsed plan to database using existing storage functions."""
    objective = plan_data.get("objective", "")
    subtasks_data = plan_data.get("subtasks", [])
    constraints = plan_data.get("constraints", [])

    spirit = get_task_spirit(task_id)
    if not spirit:
        create_task_spirit(task_id=task_id, objective=objective, constraints=constraints)
    else:
        from ...storage.task_spirit import update_task_spirit

        update_task_spirit(task_id, objective=objective, constraints=constraints)

    if subtasks_data:
        formatted_subtasks: list[dict[str, Any]] = []
        for st in subtasks_data:
            steps = st.get("steps", [])
            formatted_steps = []
            for step in steps:
                if isinstance(step, dict):
                    formatted_steps.append(
                        {
                            "description": step.get("description", ""),
                            "verify_command": step.get("verify_command"),
                            "expected_output": step.get("expected_output"),
                        }
                    )
                else:
                    formatted_steps.append({"description": str(step)})

            formatted_subtasks.append(
                {
                    "subtask_id": st.get("subtask_id", f"{len(formatted_subtasks) + 1}.1"),
                    "phase": st.get("phase"),
                    "description": st.get("description", ""),
                    "steps": formatted_steps,
                }
            )

        bulk_create_subtasks(task_id, formatted_subtasks)
        logger.info("Created subtasks from plan", task_id=task_id, count=len(formatted_subtasks))


def _route_based_on_complexity(task_id: str, title: str, description: str) -> None:
    """Route task based on complexity assessment.

    SIMPLE/STANDARD -> Queue for execution
    COMPLEX -> Human Review for discussion
    """
    assessor = ComplexityAssessor()
    result = assessor.assess_sync(title, description)

    task_store.update_task(task_id, complexity=result.tier.value)

    if result.tier == ComplexityTier.COMPLEX:
        task_store.update_task_status(task_id, "human_review")
        log_task_event(
            task_id,
            f"Complexity: {result.tier.value} - Routing to Human Review for discussion. "
            f"Reason: {result.reasoning}",
        )
        logger.info(
            "Complex task routed to human review",
            task_id=task_id,
            complexity=result.tier.value,
        )
    else:
        task_store.update_task_status(task_id, "queue")
        log_task_event(
            task_id,
            f"Complexity: {result.tier.value} - Plan ready, queued for execution.",
        )
        logger.info(
            "Task queued for execution",
            task_id=task_id,
            complexity=result.tier.value,
        )
