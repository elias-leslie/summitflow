"""Autonomous execution tasks for SummitFlow.

This module provides Celery tasks for autonomous task execution:
- Idea triage
- Planning with run_agent()
- Subtask execution with fresh context
- 3-2-1 escalation pattern
- AI review and auto-merge
"""

from __future__ import annotations

from .execution import start_execution
from .triage import triage_idea

__all__ = [
    "start_execution",
    "triage_idea",
]
