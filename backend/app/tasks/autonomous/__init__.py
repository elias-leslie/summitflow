"""Autonomous execution tasks for SummitFlow.

Plain functions called by Hatchet workflow wrappers:
- Idea triage
- Planning with run_agent()
- Subtask execution with fresh context
- 3-2-1 escalation pattern
- AI review and auto-merge
- Scheduled pickup and dispatch
"""

from __future__ import annotations

from .cleanup import merge_and_cleanup_task_worktree, reset_expired_task_claims
from .escalation import check_worker_stuck, supervisor_guidance
from .execution import start_execution
from .pickup import (
    autonomous_work_pickup,
    dispatch_task_immediate,
    review_pending_tasks,
)
from .planning import create_plan
from .review import ai_review
from .task_generation import generate_tasks_from_scan, regenerate_refactor_tasks
from .triage import triage_idea

__all__ = [
    "ai_review",
    "autonomous_work_pickup",
    "check_worker_stuck",
    "create_plan",
    "dispatch_task_immediate",
    "generate_tasks_from_scan",
    "merge_and_cleanup_task_worktree",
    "regenerate_refactor_tasks",
    "reset_expired_task_claims",
    "review_pending_tasks",
    "start_execution",
    "supervisor_guidance",
    "triage_idea",
]
