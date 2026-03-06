"""Agent routing and supervisor utilities."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from ....logging_config import get_logger
from ....services.agent_hub_client import get_sync_client
from ....storage import log_task_event
from ....storage import tasks as task_store
from .._project_resolution import resolve_task_project_id
from ._routing_maps import (
    CROSS_AGENT_FALLBACK_MAP,
    SUBTASK_TYPE_AGENT_MAP,
    TASK_TYPE_AGENT_MAP,
)

logger = get_logger(__name__)
VALID_SUBTASK_TYPES: set[str] = set(SUBTASK_TYPE_AGENT_MAP.keys())

# Routing defaults and supervisor constants
DEFAULT_AGENT = "coder"
EXTENSION_ATTEMPTS = 4
SUPERVISOR_AGENT_SLUG = "supervisor"
CONTINUE_KEYWORD = "CONTINUE"
APPROVED_KEYWORD = "APPROVED"
DIFF_SUMMARY_MAX_LEN = 200


def get_fallback_agents(subtask_type: str | None, current_agent: str) -> list[str]:
    """Return alternative agents for cross-agent fallback, excluding current."""
    if not subtask_type:
        return []
    return [a for a in CROSS_AGENT_FALLBACK_MAP.get(subtask_type, []) if a != current_agent]


def get_agent_for_subtask(subtask_type: str | None, task_type: str | None = None) -> str:
    """Get agent slug: subtask_type mapping > task_type mapping > default."""
    if subtask_type and subtask_type in SUBTASK_TYPE_AGENT_MAP:
        return SUBTASK_TYPE_AGENT_MAP[subtask_type]
    if task_type and task_type in TASK_TYPE_AGENT_MAP:
        return TASK_TYPE_AGENT_MAP[task_type]
    return DEFAULT_AGENT


def get_agent_for_task(task_type: str | None) -> str:
    """Get agent slug for a task type."""
    return TASK_TYPE_AGENT_MAP.get(task_type, DEFAULT_AGENT) if task_type else DEFAULT_AGENT


def supervisor_circuit_breaker_triage(
    task_id: str, issue_id: str, count: int, project_id: str,
) -> bool:
    """Ask supervisor if we should continue past circuit breaker. Returns True to continue."""
    prompt = (
        f"Circuit breaker triggered for task {task_id}.\n"
        f"Issue '{issue_id}' repeated {count} times across subtasks.\n\n"
        f"IMPORTANT: This system operates 99% autonomously. Only BLOCK if the issue is truly unrecoverable "
        f"(e.g., missing credentials, wrong project, fundamentally broken architecture). "
        f"For transient errors, test failures, or fixable code issues, ALWAYS reply CONTINUE.\n\n"
        f"Reply CONTINUE or BLOCK with brief reasoning."
    )
    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            agent_slug=SUPERVISOR_AGENT_SLUG,
            project_id=project_id,
        )
        # Only BLOCK if supervisor explicitly says so; default to continue
        content = response.content.upper()
        return not ("BLOCK" in content and CONTINUE_KEYWORD not in content)
    except Exception:
        logger.warning("Supervisor circuit breaker triage failed, defaulting to CONTINUE (autonomous-first)", exc_info=True)
        return True


def detect_progress(
    subtask_id: str,
    steps: list[dict[str, Any]],
    step_results: list[dict[str, Any]],
    project_path: str,
) -> dict[str, Any] | None:
    """Check if agent made measurable progress. Returns evidence dict or None."""
    evidence: dict[str, Any] = {}
    passed_count = sum(1 for r in step_results if r["passed"])
    if passed_count > 0:
        evidence["steps_passed"] = f"{passed_count}/{len(step_results)}"
    try:
        diff = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            capture_output=True, text=True, timeout=10, cwd=project_path,
        )
        if diff.stdout.strip():
            evidence["has_code_changes"] = True
            evidence["diff_summary"] = diff.stdout.strip()[-DIFF_SUMMARY_MAX_LEN:]
    except (subprocess.TimeoutExpired, OSError):
        pass
    defected = [s for s in steps if s.get("status") == "plan_defect"]
    if defected:
        evidence["adjusted_steps"] = len(defected)
    return evidence if evidence else None


def _build_extension_prompt(
    task_id: str, subtask_id: str,
    step_results: list[dict[str, Any]],
    progress: dict[str, Any],
    prior_extensions: int,
) -> str:
    """Build the supervisor prompt for an extension request."""
    failed_summary = "; ".join(
        f"Step {f['step_number']}: {f.get('reason', 'failed')}"
        for f in step_results if not f["passed"]
    )
    ext_ctx = f"\nExtension request #{prior_extensions + 1} ({prior_extensions} already granted).\n" if prior_extensions > 0 else ""
    return (
        f"Extension request for subtask {subtask_id} (task {task_id}).\n\n"
        f"Retry budget exhausted. Agent made progress:\n{json.dumps(progress, indent=2)}\n\n"
        f"Still failing:\n{failed_summary}\n{ext_ctx}\n"
        f"Should we grant {EXTENSION_ATTEMPTS} more attempts? "
        f"IMPORTANT: This system is 99% autonomous — DENY only for truly unrecoverable issues "
        f"(missing credentials, wrong project, fundamentally impossible task). "
        f"If there's ANY evidence of progress or a different approach could work, APPROVE.\n"
        f"If APPROVED, include specific guidance on what to try differently.\n"
        f"Reply APPROVED or DENIED, followed by your reasoning."
    )


def _get_project_id(task_id: str, project_id: str | None = None) -> str:
    """Resolve project scope from explicit input or task context."""
    return resolve_task_project_id(task_store.get_task(task_id), project_id)


def request_extension(
    task_id: str,
    subtask_id: str,
    step_results: list[dict[str, Any]],
    progress: dict[str, Any],
    project_id: str | None = None,
    prior_extensions: int = 0,
) -> tuple[bool, str | None]:
    """Ask supervisor whether to grant more attempts. Returns (approved, guidance)."""
    prompt = _build_extension_prompt(task_id, subtask_id, step_results, progress, prior_extensions)
    resolved_project_id = _get_project_id(task_id, project_id)
    try:
        client = get_sync_client()
        response = client.complete(
            messages=[{"role": "user", "content": prompt}],
            agent_slug=SUPERVISOR_AGENT_SLUG,
            project_id=resolved_project_id,
        )
        approved = APPROVED_KEYWORD in response.content.upper()
        log_task_event(
            task_id,
            f"Extension {'approved' if approved else 'denied'} by supervisor: {response.content[:300]}",
        )
        return approved, response.content if approved else None
    except Exception as e:
        logger.warning("Extension request failed, defaulting to APPROVED (autonomous-first)", error=str(e))
        return True, None
