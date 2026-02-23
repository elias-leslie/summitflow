"""Persona API client for the st persona CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from ..config import get_agent_hub_url


def _get_url(path: str = "") -> str:
    """Build full persona API URL."""
    return f"{get_agent_hub_url()}/api/persona{path}"


def _get_headers() -> dict[str, str]:
    """Load auth headers from ~/.env.local for Agent Hub access control."""
    env_file = Path.home() / ".env.local"
    client_id = ""
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, val = line.split("=", 1)
                if key.strip() == "SUMMITFLOW_CLIENT_ID":
                    client_id = val.strip()
                    break
    return {
        "X-Client-Id": client_id,
        "X-Request-Source": "st-persona",
    }


def get_persona() -> dict[str, Any]:
    """GET /api/persona — full persona config."""
    resp = httpx.get(_get_url(), headers=_get_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()


def update_persona(fields: dict[str, Any]) -> dict[str, Any]:
    """PUT /api/persona — partial update."""
    resp = httpx.put(_get_url(), json=fields, headers=_get_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_personality() -> dict[str, Any]:
    """GET /api/persona/personality — just the personality text."""
    resp = httpx.get(_get_url("/personality"), headers=_get_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()


def update_personality(personality: str, reason: str = "") -> dict[str, Any]:
    """PUT /api/persona/personality — update personality document."""
    resp = httpx.put(
        _get_url("/personality"),
        json={"personality": personality, "reason": reason},
        headers=_get_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()
