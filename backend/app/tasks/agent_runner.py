"""Celery tasks for agent execution.

Tasks:
- run_agent_task: Execute an agent on a specific task
"""

from __future__ import annotations

from typing import Any

from celery import shared_task

from ..logging_config import get_logger
from ..services.agent_hub_client import AgentType, get_agent
from ..storage import log_task_event, tasks

logger = get_logger(__name__)


@shared_task(  # type: ignore[untyped-decorator]
    name="summitflow.run_agent_task",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    soft_time_limit=270,  # 4.5 minutes soft limit
    time_limit=300,  # 5 minutes hard limit
)
def run_agent_task(
    self: Any,
    task_id: str,
    agent_type: AgentType,
    model: str | None = None,
) -> dict[str, Any]:
    """Execute an agent on a specific task.

    This is the main entry point for running an agent to work on a feature.
    The agent is initialized with the feature context and executes to
    implement the acceptance criteria.

    Args:
        self: Celery task instance (for retry support)
        task_id: The task ID to execute
        agent_type: Either "claude" or "gemini"
        model: Optional model override

    Returns:
        Summary dict with status, tokens_used, and completion info
    """
    logger.info(
        "agent_task_started",
        task_id=task_id,
        agent_type=agent_type,
        model=model,
    )

    # 1. Load task from database
    task = tasks.get_task(task_id)
    if not task:
        logger.error("task_not_found", task_id=task_id)
        return {"status": "error", "error": f"Task not found: {task_id}"}

    project_id = task["project_id"]

    # 2. Update task status to running
    tasks.update_task_status(task_id, "running")
    log_task_event(task_id, f"Starting agent execution with {agent_type}")

    try:
        # 3. Initialize agent
        try:
            agent = get_agent(agent_type, model)
            if not agent.is_available():
                raise RuntimeError(f"{agent_type} agent is not available")
            log_task_event(
                task_id, f"Initialized {agent_type} agent ({agent.get_model_name()})"
            )
        except Exception as e:
            logger.error("agent_init_failed", agent_type=agent_type, error=str(e))
            tasks.update_task_status(task_id, "failed", error_message=str(e))
            log_task_event(task_id, f"ERROR: Failed to initialize agent: {e}")
            return {"status": "error", "error": f"Agent init failed: {e}"}

        # 4. Build context prompt
        context = _build_agent_context(task)
        log_task_event(task_id, "Built context for agent")

        # 6. Execute agent
        log_task_event(task_id, "Sending prompt to agent...")

        try:
            response = agent.generate(
                prompt=context,
                system=_get_system_prompt(project_id),
            )
            # Support both naming conventions (Claude uses input_tokens, Gemini uses prompt_tokens)
            input_tokens = response.usage.get("input_tokens") or response.usage.get(
                "prompt_tokens", 0
            )
            output_tokens = response.usage.get("output_tokens") or response.usage.get(
                "completion_tokens", 0
            )
            log_task_event(
                task_id,
                f"Agent response received ({input_tokens} in, {output_tokens} out)",
            )
        except Exception as e:
            logger.error("agent_execution_failed", task_id=task_id, error=str(e))
            # Retry on transient failures
            try:
                raise self.retry(exc=e)
            except self.MaxRetriesExceededError:
                tasks.update_task_status(
                    task_id, "failed", error_message=f"Agent execution failed: {e}"
                )
                log_task_event(task_id, f"ERROR: Agent failed after retries: {e}")
                return {"status": "error", "error": str(e)}

        # 7. Update task with results
        total_tokens = input_tokens + output_tokens
        tasks.update_task(
            task_id,
            total_tokens_used=(task.get("total_tokens_used") or 0) + total_tokens,
            total_sessions=(task.get("total_sessions") or 0) + 1,
        )

        # 8. Log agent output
        # Truncate very long outputs for the log
        output_preview = (
            response.content[:500] + "..." if len(response.content) > 500 else response.content
        )
        log_task_event(task_id, f"Agent output:\n{output_preview}")

        # 9. Mark task as completed (for now - Phase 6 will add criterion-by-criterion)
        tasks.update_task_status(task_id, "completed")
        log_task_event(task_id, "Task completed successfully")

        logger.info(
            "agent_task_completed",
            task_id=task_id,
            tokens_used=total_tokens,
        )

        return {
            "status": "success",
            "task_id": task_id,
            "tokens_used": total_tokens,
            "output_length": len(response.content),
            "agent": agent_type,
            "model": agent.get_model_name(),
        }

    except Exception as e:
        logger.error("agent_task_unexpected_error", task_id=task_id, error=str(e))
        tasks.update_task_status(task_id, "failed", error_message=str(e))
        log_task_event(task_id, f"ERROR: Unexpected error: {e}")
        return {"status": "error", "error": str(e)}


def _build_agent_context(task: dict[str, Any]) -> str:
    """Build the context prompt for the agent.

    Args:
        task: Task dict from database

    Returns:
        Formatted context string for the agent
    """
    parts = [f"# Task: {task['title']}"]

    if task.get("description"):
        parts.append(f"\n## Description\n{task['description']}")

    if task.get("spec_content"):
        parts.append(f"\n## Specification\n{task['spec_content']}")

    if task.get("plan_content"):
        import json

        plan = task["plan_content"]
        if isinstance(plan, str):
            plan = json.loads(plan)
        parts.append(f"\n## Plan\n{json.dumps(plan, indent=2)}")

    parts.append(
        "\n## Instructions\n"
        "Analyze the feature and acceptance criteria above. "
        "For each pending criterion, outline the steps needed to implement it. "
        "Focus on concrete, actionable implementation details."
    )

    return "\n".join(parts)


def _get_system_prompt(project_id: str) -> str:
    """Get the system prompt for the agent.

    Args:
        project_id: Project ID for context

    Returns:
        System prompt string
    """
    return f"""You are an AI development assistant working on project '{project_id}'.

Your role is to help implement features by:
1. Analyzing requirements and acceptance criteria
2. Proposing concrete implementation steps
3. Identifying potential issues or blockers
4. Suggesting file changes needed

Be specific and actionable. Reference exact file paths and code locations where possible.
Format your response clearly with sections for each criterion you're addressing."""
