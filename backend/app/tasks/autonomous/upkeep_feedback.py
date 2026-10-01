"""Compatibility entrypoints: feedback is passive decision intelligence.

Task creation, approval and dispatch require an explicit orchestrator decision.
Scheduled or forced upkeep cannot promote captured feedback. Existing feedback
links remain available through the ordinary feedback PATCH/CLI link interface.
"""

from typing import Any


def feedback_task_from_item(project_id: str, feedback: dict[str, Any]) -> None:
    """Never turn an observation into autonomous work."""
    return None


def create_feedback_tasks(project_id: str, limit: int) -> list[str]:
    """Retained for compatibility; captures and upkeep create zero feedback tasks."""
    return []
