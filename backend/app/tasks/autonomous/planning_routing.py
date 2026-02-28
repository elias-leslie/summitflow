"""Complexity-based routing for autonomous planning."""

from __future__ import annotations

from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...services.complexity_assessor import ComplexityAssessor, ComplexityTier
from ...storage import log_task_event
from ...storage import tasks as task_store

logger = get_logger(__name__)


def supervisor_validate_plan(task_id: str, reasoning: str, project_id: str) -> bool:
    """Ask supervisor to validate a COMPLEX plan.

    Args:
        task_id: Task ID to validate
        reasoning: Complexity assessor reasoning
        project_id: Project ID for agent context

    Returns:
        True to proceed, False to block
    """
    prompt = (
        f"Task {task_id} was classified as COMPLEX.\n"
        f"Assessor reasoning: {reasoning}\n\n"
        f"Should this task proceed to execution? "
        f"Reply APPROVED to proceed or BLOCKED with your concern."
    )
    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            agent_slug="supervisor",
            project_id=project_id,
        )
        return "BLOCKED" not in response.content.upper()
    except Exception:
        logger.warning("Supervisor plan validation failed, defaulting to proceed", exc_info=True)
        return True


def route_based_on_complexity(task_id: str, title: str, description: str) -> None:
    """Route task based on complexity assessment.

    SIMPLE/STANDARD -> Queue for execution
    COMPLEX -> Supervisor validates, then queue or blocked

    Args:
        task_id: Task ID to route
        title: Task title
        description: Task description
    """
    task = task_store.get_task(task_id)
    project_id = task.get("project_id", "summitflow") if task else "summitflow"

    # Respect existing complexity if already set (e.g. from plan import)
    existing_complexity = task.get("complexity") if task else None
    if existing_complexity:
        try:
            tier = ComplexityTier(existing_complexity)
        except ValueError:
            tier = None
        if tier:
            result_tier = tier
            result_reasoning = f"Pre-set complexity: {existing_complexity}"
        else:
            assessor = ComplexityAssessor()
            assessed = assessor.assess_sync(title, description)
            result_tier = assessed.tier
            result_reasoning = assessed.reasoning
            task_store.update_task(task_id, complexity=result_tier.value)
    else:
        assessor = ComplexityAssessor()
        assessed = assessor.assess_sync(title, description)
        result_tier = assessed.tier
        result_reasoning = assessed.reasoning
        task_store.update_task(task_id, complexity=result_tier.value)

    if result_tier == ComplexityTier.COMPLEX:
        approved = supervisor_validate_plan(task_id, result_reasoning, project_id)
        if approved:
            task_store.update_task_status(task_id, "queue")
            log_task_event(
                task_id,
                f"Complexity: {result_tier.value} - Supervisor approved, queued for execution. "
                f"Reason: {result_reasoning}",
            )
            logger.info(
                "Complex task supervisor-approved, queued",
                task_id=task_id,
                complexity=result_tier.value,
            )
        else:
            task_store.update_task_status(task_id, "blocked")
            log_task_event(
                task_id,
                f"Complexity: {result_tier.value} - Supervisor blocked task. "
                f"Reason: {result_reasoning}",
            )
            logger.info(
                "Complex task blocked by supervisor",
                task_id=task_id,
                complexity=result_tier.value,
            )
    else:
        task_store.update_task_status(task_id, "queue")
        log_task_event(
            task_id,
            f"Complexity: {result_tier.value} - Plan ready, queued for execution.",
        )
        logger.info(
            "Task queued for execution",
            task_id=task_id,
            complexity=result_tier.value,
        )
