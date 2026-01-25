"""Autonomous execution tasks for SummitFlow.

This module provides Celery tasks for autonomous task execution:
- Idea triage
- Planning with run_agent()
- Subtask execution with fresh context
- 3-2-1 escalation pattern
- AI review and auto-merge
- Scheduled pickup and dispatch
"""

from __future__ import annotations

from .escalation import check_worker_stuck, supervisor_guidance
from .execution import start_execution
from .pickup import autonomous_work_pickup, review_pending_tasks
from .planning import create_plan
from .review import ai_review
from .triage import triage_idea

__all__ = [
    "ai_review",
    "autonomous_work_pickup",
    "check_worker_stuck",
    "create_plan",
    "review_pending_tasks",
    "start_execution",
    "supervisor_guidance",
    "triage_idea",
]
