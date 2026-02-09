"""Helper utilities for task commands."""

from __future__ import annotations

from typing import Any


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
    except Exception:
        pass
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
    except Exception:
        pass
    return []
