"""Persona API client for the st persona CLI."""

from __future__ import annotations

from typing import Any

import httpx

from ..config import get_agent_hub_url


def _get_url(path: str = "") -> str:
    """Build full persona API URL."""
    return f"{get_agent_hub_url()}/api/persona{path}"


def get_persona() -> dict[str, Any]:
    """GET /api/persona — full persona config."""
    resp = httpx.get(_get_url(), timeout=10)
    resp.raise_for_status()
    return resp.json()


def update_persona(fields: dict[str, Any]) -> dict[str, Any]:
    """PUT /api/persona — partial update."""
    resp = httpx.put(_get_url(), json=fields, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_personality() -> dict[str, Any]:
    """GET /api/persona/personality — just the personality text."""
    resp = httpx.get(_get_url("/personality"), timeout=10)
    resp.raise_for_status()
    return resp.json()


def update_personality(personality: str, reason: str = "") -> dict[str, Any]:
    """PUT /api/persona/personality — update personality document."""
    resp = httpx.put(
        _get_url("/personality"),
        json={"personality": personality, "reason": reason},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()
