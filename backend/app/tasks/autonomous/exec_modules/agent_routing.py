"""Agent routing and supervisor utilities."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from ....logging_config import get_logger
from ....services.agent_hub_client import get_sync_client
from ....storage import log_task_event

logger = get_logger(__name__)

# Map task_type to agent_slug for specialized execution
TASK_TYPE_AGENT_MAP: dict[str, str] = {
    "refactor": "refactor",
    "bug": "debugger",
    "feature": "coder",
}
DEFAULT_AGENT = "coder"
EXTENSION_ATTEMPTS = 4

# Map subtask_type to agent_slug for per-subtask routing
# Planner assigns subtask_type during planning; execution routes accordingly
SUBTASK_TYPE_AGENT_MAP: dict[str, str] = {
    "backend": "coder",
    "frontend": "coder",
    "ui-design": "ux-polisher",
    "refactor": "refactor",
    "bug-fix": "debugger",
    "test": "test-writer",
    "performance": "optimizer",
    "config": "coder",
    "devops": "coder",
}

VALID_SUBTASK_TYPES = set(SUBTASK_TYPE_AGENT_MAP.keys())

# Cross-agent fallback: when primary agent fails after escalation,
# try these alternative agents (in order)
CROSS_AGENT_FALLBACK_MAP: dict[str, list[str]] = {
    "backend": ["debugger", "refactor"],
    "frontend": ["debugger", "ux-polisher"],
    "ui-design": ["coder"],
    "bug-fix": ["coder", "refactor"],
    "test": ["coder"],
    "performance": ["coder", "debugger"],
    "refactor": ["coder"],
    "config": ["debugger"],
    "devops": ["coder"],
}


def get_fallback_agents(subtask_type: str | None, current_agent: str) -> list[str]:
    """Get alternative agent slugs for cross-agent fallback.

    Returns agents to try after the primary agent fails, excluding the current one.
    """
    if not subtask_type:
        return []
    fallbacks = CROSS_AGENT_FALLBACK_MAP.get(subtask_type, [])
    return [a for a in fallbacks if a != current_agent]


def get_agent_for_subtask(
    subtask_type: str | None, task_type: str | None = None
) -> str:
    """Get the appropriate agent slug, preferring subtask_type over task_type.

    Resolution order: subtask_type mapping > task_type mapping > default ("coder")

    Args:
        subtask_type: The subtask type (backend, frontend, bug-fix, etc.)
        task_type: Fallback task-level type (refactor, bug, feature, etc.)

    Returns:
        Agent slug to use for execution
    """
    if subtask_type and subtask_type in SUBTASK_TYPE_AGENT_MAP:
        return SUBTASK_TYPE_AGENT_MAP[subtask_type]
    if task_type and task_type in TASK_TYPE_AGENT_MAP:
        return TASK_TYPE_AGENT_MAP[task_type]
    return DEFAULT_AGENT


def get_agent_for_task(task_type: str | None) -> str:
    """Get the appropriate agent slug for a task type.

    Args:
        task_type: The task type (refactor, bug, feature, etc.)

    Returns:
        Agent slug to use for execution
    """
    if not task_type:
        return DEFAULT_AGENT
    return TASK_TYPE_AGENT_MAP.get(task_type, DEFAULT_AGENT)


def supervisor_circuit_breaker_triage(
    task_id: str, issue_id: str, count: int, project_id: str,
) -> bool:
    """Ask supervisor if we should continue past circuit breaker. Returns True to continue."""
    prompt = (
        f"Circuit breaker triggered for task {task_id}.\n"
        f"Issue {issue_id} repeated {count} times across subtasks.\n\n"
        f"Should we continue with remaining subtasks or stop?\n"
        f"Reply CONTINUE or BLOCK."
    )
    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            agent_slug="supervisor",
            project_id=project_id,
        )
        return "CONTINUE" in response.content.upper()
    except Exception:
        return False


def detect_progress(
    subtask_id: str,
    steps: list[dict[str, Any]],
    step_results: list[dict[str, Any]],
    project_path: str,
) -> dict[str, Any] | None:
    """Check if the agent made measurable progress. Returns evidence dict or None."""
    evidence: dict[str, Any] = {}

    passed_count = sum(1 for r in step_results if r["passed"])
    total = len(step_results)
    if passed_count > 0:
        evidence["steps_passed"] = f"{passed_count}/{total}"

    try:
        diff_stat = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=project_path,
        )
        if diff_stat.stdout.strip():
            evidence["has_code_changes"] = True
            evidence["diff_summary"] = diff_stat.stdout.strip()[-200:]
    except (subprocess.TimeoutExpired, OSError):
        pass

    defected = [s for s in steps if s.get("status") == "plan_defect"]
    if defected:
        evidence["adjusted_steps"] = len(defected)

    return evidence if evidence else None


def request_extension(
    task_id: str,
    subtask_id: str,
    step_results: list[dict[str, Any]],
    progress: dict[str, Any],
    project_id: str | None = None,
    prior_extensions: int = 0,
) -> tuple[bool, str | None]:
    """Ask supervisor whether to grant more attempts.

    Returns (approved, guidance) — guidance is the supervisor's reasoning/advice
    for the extended attempts, fed back to the agent as fresh direction.
    """
    failed = [r for r in step_results if not r["passed"]]
    failed_summary = "; ".join(
        f"Step {f['step_number']}: {f.get('reason', 'failed')}" for f in failed
    )

    ext_context = ""
    if prior_extensions > 0:
        ext_context = (
            f"\nThis is extension request #{prior_extensions + 1} "
            f"({prior_extensions} already granted).\n"
        )

    prompt = (
        f"Extension request for subtask {subtask_id} (task {task_id}).\n\n"
        f"Retry budget exhausted. Agent made progress:\n"
        f"{json.dumps(progress, indent=2)}\n\n"
        f"Still failing:\n{failed_summary}\n"
        f"{ext_context}\n"
        f"Should we grant {EXTENSION_ATTEMPTS} more attempts? "
        f"If APPROVED, include specific guidance for the agent "
        f"on what to try differently — they have been stuck, "
        f"so a fresh approach is needed.\n"
        f"Reply APPROVED or DENIED, followed by your reasoning."
    )

    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            agent_slug="supervisor",
            project_id=project_id or "summitflow",
        )
        approved = "APPROVED" in response.content.upper()
        log_task_event(
            task_id,
            f"Extension {'approved' if approved else 'denied'} by supervisor: "
            f"{response.content[:300]}",
        )
        return approved, response.content if approved else None
    except Exception as e:
        logger.warning("Extension request failed", error=str(e))
        return False, None
