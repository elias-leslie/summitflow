"""Agent Hub's Codex transcript collector, as SummitFlow's st commands use it.

Agent Hub owns the collector (scripts/codex-session-sync.py and its scripts/lib
modules). st reads native Codex provenance through that same library from Agent
Hub's registered checkout instead of keeping a second copy.
"""

from __future__ import annotations

import os
import sys
from importlib import import_module
from pathlib import Path
from types import ModuleType

AGENT_HUB_PROJECT_ID = "agent-hub"
_ROOT_OVERRIDE = "ST_AGENT_HUB_ROOT"


def agent_hub_root() -> Path:
    """Agent Hub's registered checkout (``ST_AGENT_HUB_ROOT`` overrides for tests)."""
    override = os.environ.get(_ROOT_OVERRIDE)
    if override:
        return Path(override).expanduser()
    from ..config import get_project_root_path

    root = get_project_root_path(AGENT_HUB_PROJECT_ID)
    if not root:
        raise ImportError("Agent Hub has no registered root; its Codex collector is unavailable")
    return Path(root)


def collector_script() -> Path:
    return agent_hub_root() / "scripts" / "codex-session-sync.py"


def collector_module(name: str) -> ModuleType:
    """Import one of the collector's library modules (codex_sync_*)."""
    library = str(agent_hub_root() / "scripts" / "lib")
    if library not in sys.path:
        sys.path.insert(0, library)
    return import_module(name)
