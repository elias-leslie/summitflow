"""Complexity-based routing for autonomous planning."""

from __future__ import annotations

from ...logging_config import get_logger
from ...services.agent_hub_client import get_sync_client
from ...services.complexity_assessor import ComplexityAssessor, ComplexityTier
from ...storage import log_task_event
from ...storage import tasks as task_store
from ._project_resolution import resolve_task_project_id

logger = get_logger(__name__)

# Constants
_STATUS_QUEUE = "queue"
_STATUS_BLOCKED = "blocked"
_AGENT_SUPERVISOR = "supervisor"
_SUPERVISOR_BLOCKED_KEYWORD = "BLOCKED"

_VALIDATE_PLAN_PROMPT = (
    "Task {task_id} was classified as COMPLEX.\n"
    "Assessor reasoning: {reasoning}\n\n"
    "Should this task proceed to execution? "
    "Reply APPROVED to proceed or BLOCKED with your concern."
)


def _get_project_id(task_id: str, task: dict[str, object] | None = None) -> str:
    """Resolve project scope from the task, falling back only if missing."""
    if task is None:
        task = task_store.get_task(task_id)
    return resolve_task_project_id(task)


def supervisor_validate_plan(task_id: str, reasoning: str, project_id: str) -> bool:
    """Ask supervisor to validate a COMPLEX plan.

    Args:
        task_id: Task ID to validate
        reasoning: Complexity assessor reasoning
        project_id: Project ID for agent context

    Returns:
        True to proceed, False to block
    """
    prompt = _VALIDATE_PLAN_PROMPT.format(task_id=task_id, reasoning=reasoning)
    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            agent_slug=_AGENT_SUPERVISOR,
            project_id=project_id,
        )
        return _SUPERVISOR_BLOCKED_KEYWORD not in response.content.upper()
    except Exception:
        logger.warning("Supervisor plan validation failed, defaulting to proceed", exc_info=True)
        return True


def _resolve_complexity_tier(
    task_id: str, title: str, description: str, existing_complexity: str | None
) -> tuple[ComplexityTier, str]:
    """Determine the complexity tier, either from existing value or via assessment.

    Args:
        task_id: Task ID (used when persisting a newly assessed tier)
        title: Task title (used for fresh assessment)
        description: Task description (used for fresh assessment)
        existing_complexity: Pre-set complexity string, or None

    Returns:
        Tuple of (ComplexityTier, reasoning string)
    """
    if existing_complexity:
        try:
            tier = ComplexityTier(existing_complexity)
            return tier, f"Pre-set complexity: {existing_complexity}"
        except ValueError:
            pass

    assessor = ComplexityAssessor()
    assessed = assessor.assess_sync(title, description)
    task_store.update_task(task_id, complexity=assessed.tier.value)
    return assessed.tier, assessed.reasoning


def _apply_complex_routing(task_id: str, project_id: str, tier: ComplexityTier, reasoning: str) -> None:
    """Handle routing for COMPLEX tasks: supervisor approval or block.

    Args:
        task_id: Task ID to route
        project_id: Project ID for supervisor context
        tier: Resolved complexity tier
        reasoning: Complexity reasoning string
    """
    approved = supervisor_validate_plan(task_id, reasoning, project_id)
    if approved:
        task_store.update_task_status(task_id, _STATUS_QUEUE)
        log_task_event(
            task_id,
            f"Complexity: {tier.value} - Supervisor approved, queued for execution. "
            f"Reason: {reasoning}",
        )
        logger.info(
            "Complex task supervisor-approved, queued",
            task_id=task_id,
            complexity=tier.value,
        )
    else:
        task_store.update_task_status(task_id, _STATUS_BLOCKED)
        log_task_event(
            task_id,
            f"Complexity: {tier.value} - Supervisor blocked task. "
            f"Reason: {reasoning}",
        )
        logger.info(
            "Complex task blocked by supervisor",
            task_id=task_id,
            complexity=tier.value,
        )


def _apply_simple_routing(task_id: str, tier: ComplexityTier, reasoning: str) -> None:
    """Handle routing for SIMPLE/STANDARD tasks: queue directly.

    Args:
        task_id: Task ID to route
        tier: Resolved complexity tier
        reasoning: Complexity reasoning string (unused but kept for symmetry)
    """
    task_store.update_task_status(task_id, _STATUS_QUEUE)
    log_task_event(
        task_id,
        f"Complexity: {tier.value} - Plan ready, queued for execution.",
    )
    logger.info(
        "Task queued for execution",
        task_id=task_id,
        complexity=tier.value,
    )


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
    project_id = _get_project_id(task_id, task=task)
    existing_complexity = task.get("complexity") if task else None

    result_tier, result_reasoning = _resolve_complexity_tier(
        task_id, title, description, existing_complexity
    )

    if result_tier == ComplexityTier.COMPLEX:
        _apply_complex_routing(task_id, project_id, result_tier, result_reasoning)
    else:
        _apply_simple_routing(task_id, result_tier, result_reasoning)
