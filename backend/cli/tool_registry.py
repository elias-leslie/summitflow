"""Shared CLI access to the SummitFlow tool registry."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_PATH = _REPO_ROOT / "scripts" / "lib" / "tool-registry.json"


@lru_cache(maxsize=1)
def load_tool_registry() -> dict[str, Any]:
    """Load the shared tool registry once per process."""
    return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))


def list_operator_tools() -> list[dict[str, Any]]:
    """Return operator-tool catalog entries from the shared registry."""
    registry = load_tool_registry()
    tools = registry.get("operator_tools", [])
    return [tool for tool in tools if isinstance(tool, dict)]


def tool_registry_path() -> Path:
    """Expose registry path for diagnostics and tests."""
    return _REGISTRY_PATH
