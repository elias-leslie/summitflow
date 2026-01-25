"""Subtask execution task using Agent Hub run_agent().

Executes subtasks with fresh context per subtask to prevent context rot.
"""

from __future__ import annotations

import subprocess
from typing import Any

from celery import Task as CeleryTask
from celery import shared_task

from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...storage import tasks as task_store
from ...storage.steps import update_step_passes
from ...storage.subtasks import (
    get_handoff_context,
    get_subtasks_for_task,
    insert_subtask_summary,
    update_subtask_passes,
)
from ...storage.task_spirit import get_task_spirit

logger = get_logger(__name__)


@shared_task(bind=True, name="autonomous.start_execution")  # type: ignore[untyped-decorator]
def start_execution(self: CeleryTask, task_id: str, project_id: str) -> dict[str, Any]:
    """Start autonomous execution of a task.

    Executes subtasks in order with fresh context per subtask.
    Uses run_agent() with the worker agent for implementation.

    Args:
        task_id: The task ID to execute
        project_id: The project ID

    Returns:
        Execution result with status
    """
    logger.info("Starting autonomous execution", task_id=task_id, project_id=project_id)

    task = task_store.get_task(task_id)
    if not task:
        return {"task_id": task_id, "status": "error", "message": "Task not found"}

    task_store.update_task_status(task_id, "running")

    subtasks = get_subtasks_for_task(task_id, include_steps=True)
    incomplete = [s for s in subtasks if not s.get("passes")]

    if not incomplete:
        task_store.update_task_status(task_id, "completed")
        return {"task_id": task_id, "status": "completed", "message": "All subtasks complete"}

    results: list[dict[str, Any]] = []
    for subtask in incomplete:
        result = _execute_subtask(task_id, subtask, project_id)
        results.append(result)
        if result.get("status") == "failed":
            break

    all_passed = all(r.get("status") == "passed" for r in results)
    if all_passed and len(results) == len(incomplete):
        task_store.update_task_status(task_id, "pr_created")

    return {"task_id": task_id, "status": "executed", "subtask_results": results}


def _execute_subtask(task_id: str, subtask: dict[str, Any], project_id: str) -> dict[str, Any]:
    """Execute a single subtask with fresh context."""
    subtask_id = subtask.get("id", "")
    subtask_short_id = subtask.get("subtask_id", "")

    logger.info("Executing subtask", task_id=task_id, subtask_id=subtask_short_id)

    prompt = _build_subtask_prompt(task_id, subtask)
    worktree_path = f"/home/kasadis/{project_id}"

    try:
        client = get_sync_client()
        response = client.run_agent(
            task=prompt,
            agent_slug="coder",
            working_dir=worktree_path,
            max_turns=30,
        )

        steps = subtask.get("steps_from_table", [])
        step_results = _verify_steps(subtask_id, steps)

        all_passed = all(r["passed"] for r in step_results)
        if all_passed:
            update_subtask_passes(task_id, subtask_short_id, passes=True)
            _extract_handoff_summary(subtask_id, response.content)

        return {
            "subtask_id": subtask_short_id,
            "status": "passed" if all_passed else "failed",
            "step_results": step_results,
        }

    except Exception as e:
        logger.warning("Subtask execution failed", subtask_id=subtask_short_id, error=str(e))
        return {"subtask_id": subtask_short_id, "status": "failed", "error": str(e)}


def _build_subtask_prompt(task_id: str, subtask: dict[str, Any]) -> str:
    """Build subtask prompt with fresh context: objective + subtask + handoff only."""
    spirit = get_task_spirit(task_id)
    objective = spirit.get("objective", "") if spirit else ""

    subtask_short_id = subtask.get("subtask_id", "")
    handoff = get_handoff_context(task_id, subtask_short_id)

    prompt_parts = [f"# Task Objective\n{objective}"]

    if handoff.get("previous_summaries"):
        prompt_parts.append("\n# Previous Work Summary")
        for summary in handoff["previous_summaries"]:
            prompt_parts.append(f"- Subtask {summary['short_id']}: {summary['summary']}")

    prompt_parts.append(f"\n# Current Subtask: {subtask_short_id}")
    prompt_parts.append(f"Description: {subtask.get('description', '')}")

    steps = subtask.get("steps_from_table", [])
    if steps:
        prompt_parts.append("\nSteps to complete:")
        for step in steps:
            step_num = step.get("step_number", 0)
            desc = step.get("description", "")
            verify = step.get("verify_command", "")
            expect = step.get("expected_output", "")
            prompt_parts.append(f"{step_num}. {desc}")
            if verify:
                prompt_parts.append(f"   Verify: {verify}")
            if expect:
                prompt_parts.append(f"   Expected: {expect}")

    return "\n".join(prompt_parts)


def _verify_steps(subtask_id: str, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run verify_command for each step and check expected_output."""
    results: list[dict[str, Any]] = []

    for step in steps:
        step_num = step.get("step_number", 0)
        verify_cmd = step.get("verify_command")
        expected = step.get("expected_output", "")

        if not verify_cmd:
            results.append({"step_number": step_num, "passed": True, "reason": "no_verify"})
            update_step_passes(subtask_id, step_num, True)
            continue

        try:
            result = subprocess.run(
                verify_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
                cwd="/home/kasadis/summitflow",
            )
            output = result.stdout.strip()
            passed = expected in output if expected else result.returncode == 0

            update_step_passes(subtask_id, step_num, passed)
            results.append({
                "step_number": step_num,
                "passed": passed,
                "output": output[:500],
                "expected": expected,
            })

        except subprocess.TimeoutExpired:
            results.append({"step_number": step_num, "passed": False, "reason": "timeout"})
        except Exception as e:
            results.append({"step_number": step_num, "passed": False, "error": str(e)})

    return results


def _extract_handoff_summary(subtask_id: str, agent_response: str) -> None:
    """Extract and save handoff summary from agent response."""
    summary = agent_response[:1000] if len(agent_response) > 1000 else agent_response
    insert_subtask_summary(subtask_id, summary=summary, files_modified=[], decisions_made=[])
