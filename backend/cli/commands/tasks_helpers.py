"""Helper utilities for task commands."""

from __future__ import annotations

import logging
from typing import Any

import typer

logger = logging.getLogger(__name__)


def build_subtasks_data(subtasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert plan subtasks into API-ready subtask dicts."""
    result = []
    for st in subtasks:
        sid = st["id"]
        parts = sid.split(".")
        try:
            order = int(parts[0]) * 100 + int(parts[1]) if len(parts) >= 2 else 0
        except ValueError:
            order = 0
        entry: dict[str, Any] = {
            "subtask_id": sid, "phase": st.get("phase"),
            "description": st["description"], "steps": st.get("steps", []),
            "display_order": order, "subtask_type": st.get("subtask_type"),
        }
        if st.get("depends_on"):
            entry["depends_on"] = st["depends_on"]
        result.append(entry)
    return result


def upsert_task_spirit_from_plan(task_id: str, plan: dict[str, Any]) -> dict[str, Any] | None:
    """Upsert task_spirit record for plan data."""
    from app.services.task_execution_readiness import sync_task_execution_readiness
    from app.services.task_plan_context import build_task_plan_context
    from app.services.task_second_opinion import ensure_second_opinion_tracking
    from app.storage import tasks as task_store
    from app.storage.task_spirit import upsert_task_spirit
    try:
        context_blob = build_task_plan_context(plan)
        upsert_task_spirit(
            task_id=task_id,
            done_when=plan.get("done_when"), context=context_blob if context_blob else None,
            complexity=plan.get("complexity", "SIMPLE"),
        )
        task = task_store.get_task(task_id)
        second_opinion = (
            ensure_second_opinion_tracking(task_id, task, source="plan-import")
            if task else None
        )
        sync_task_execution_readiness(task_id, approved_by="plan-import")
        return second_opinion
    except Exception as e:
        typer.echo(f"  Warning: Failed to write task_spirit: {e}")
        return None


def create_subtask_dependencies(task_id: str, subtasks: list[dict[str, Any]]) -> None:
    """Create subtask dependencies from plan data."""
    from app.storage.subtask_dependencies import bulk_add_dependencies
    deps: list[tuple[str, str]] = [
        (f"{task_id}-{sub['subtask_id']}", f"{task_id}-{dep}")
        for sub in subtasks if sub.get("depends_on")
        for dep in sub["depends_on"]
    ]
    if deps:
        try:
            bulk_add_dependencies(deps)
        except Exception as dep_err:
            typer.echo(f"  Warning: Failed to create dependencies: {dep_err}")


def fetch_triggered_references(task_type: str) -> list[dict[str, Any]]:
    """Fetch task-type triggered references from Agent Hub."""
    import httpx

    from ..config import get_agent_hub_url

    try:
        url = f"{get_agent_hub_url()}/api/memory/triggered-references"
        response = httpx.get(url, params={"task_type": task_type}, timeout=5.0)
        if response.status_code == 200:
            data: dict[str, Any] = response.json()
            refs: list[dict[str, Any]] = data.get("references", [])
            return refs
    except (httpx.HTTPError, OSError):
        logger.debug("Failed to fetch triggered references for %s", task_type)
    return []


def fetch_phase_triggered_references(phase: str) -> list[dict[str, Any]]:
    """Fetch phase-triggered references from Agent Hub."""
    import httpx

    from ..config import get_agent_hub_url

    try:
        url = f"{get_agent_hub_url()}/api/memory/phase-triggered-references"
        response = httpx.get(url, params={"phase": phase}, timeout=5.0)
        if response.status_code == 200:
            data: dict[str, Any] = response.json()
            refs: list[dict[str, Any]] = data.get("references", [])
            return refs
    except (httpx.HTTPError, OSError):
        logger.debug("Failed to fetch phase references for %s", phase)
    return []
