"""CLI configuration management."""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx

from app.config import DEFAULT_API_BASE
from app.services._agent_hub_config import AGENT_HUB_URL as _RESOLVED_AGENT_HUB_URL

from .lib.execution_context import canonical_repo_root

logger = logging.getLogger(__name__)
_RETRY_DELAY = 0.5
_PROJECT_NOT_FOUND_MSG = (
    "Error: Could not determine project.\n\n"
    "Options:\n"
    "  1. Run from within a registered project directory\n"
    "  2. Set ST_PROJECT_ID environment variable\n"
    "  3. Use --project / -P flag: st -P myproject list\n\n"
    "List available projects: st projects"
)


def get_agent_hub_url() -> str:
    """Get Agent Hub API URL (AGENT_HUB_URL env var, fallback localhost:8003)."""
    return _RESOLVED_AGENT_HUB_URL


@dataclass(frozen=True)
class Config:
    """CLI configuration loaded from environment variables or auto-detected."""

    api_base: str
    project_id: str
    project_root: str | None = None
    source: str = "unknown"


# Module-level override (set by --project flag in main.py)
_project_override: str | None = None


def set_project_override(project_id: str | None) -> None:
    """Set project override from --project flag and clear config cache."""
    global _project_override
    _project_override = project_id
    get_config.cache_clear()


def _resolve_project_from_list(projects: list[object], cwd: Path) -> tuple[str | None, str | None]:
    """Return (project_id, root_path) for the project containing cwd, or (None, None)."""
    for project in projects:
        if not isinstance(project, dict):
            continue
        root_path = project.get("root_path")
        if not root_path:
            continue
        root = Path(str(root_path)).resolve()
        try:
            cwd.relative_to(root)
            return project.get("id"), str(root)
        except ValueError:
            continue
    return None, None


def _parse_projects_response(response: httpx.Response) -> list[object] | str | None:
    """Parse /projects response. Returns list on success, str (error msg) on bad status, None on bad format."""
    if response.status_code != 200:
        return f"status={response.status_code}"
    data = response.json()
    if not isinstance(data, list):
        return None
    return data


def _fetch_projects_with_retry(api_base: str, max_retries: int) -> list[object] | None:
    """Fetch /projects with retry on transient failures; return None on permanent failure."""
    for attempt in range(max_retries):
        try:
            response = httpx.get(f"{api_base}/projects", timeout=5.0)
        except httpx.TimeoutException as e:
            logger.warning("Project detection timeout (attempt %d/%d): %s", attempt + 1, max_retries, e)
        except httpx.RequestError as e:
            logger.warning("Project detection network error (attempt %d/%d): %s", attempt + 1, max_retries, e)
        except Exception as e:
            logger.error("Project detection unexpected error: %s", e)
            return None
        else:
            result = _parse_projects_response(response)
            if isinstance(result, list):
                return result
            if result is None:
                logger.warning("Project detection: API returned non-list response")
                return None
            logger.warning("Project detection: API returned %s (attempt %d/%d)", result, attempt + 1, max_retries)
        if attempt < max_retries - 1:
            time.sleep(_RETRY_DELAY * (attempt + 1))
    return None


def _detect_project_from_cwd(api_base: str, max_retries: int = 3) -> tuple[str | None, str | None]:
    """Detect project_id/root_path from cwd by querying projects API.

    Returns:
        Tuple of (project_id, root_path) or (None, None) if not found.
    """
    projects = _fetch_projects_with_retry(api_base, max_retries)
    if projects is None:
        return None, None
    cwd = Path.cwd().resolve()
    project_id, root_path = _resolve_project_from_list(projects, cwd)
    if project_id:
        return project_id, root_path

    canonical_root = canonical_repo_root(cwd)
    if canonical_root and canonical_root != cwd:
        project_id, root_path = _resolve_project_from_list(projects, canonical_root)
        if project_id:
            return project_id, root_path

    return None, None


def _resolve_project(api_base: str) -> tuple[str | None, str | None, str]:
    """Resolve (project_id, root_path, source) using priority: override > env > cwd detection.

    Source is one of: "flag", "env", "cwd", "unknown".
    """
    if _project_override:
        return _project_override, None, "flag"
    env_project = os.getenv("ST_PROJECT_ID")
    if env_project:
        return env_project, None, "env"
    project_id, root_path = _detect_project_from_cwd(api_base)
    return project_id, root_path, "cwd"


@lru_cache
def get_config() -> Config:
    """Get CLI configuration (exits with error if no project can be determined).

    Priority: --project flag > ST_PROJECT_ID env > cwd auto-detect.
    """
    api_base = os.getenv("ST_API_BASE", DEFAULT_API_BASE)
    project_id, project_root, source = _resolve_project(api_base)
    if project_id:
        return Config(api_base=api_base, project_id=project_id, project_root=project_root, source=source)
    print(_PROJECT_NOT_FOUND_MSG, file=sys.stderr)
    sys.exit(1)


def get_config_optional() -> Config:
    """Get CLI configuration without requiring a project.

    Same as get_config() but returns Config with empty project_id instead of
    exiting. Useful for commands that operate without project context.
    """
    api_base = os.getenv("ST_API_BASE", DEFAULT_API_BASE)
    project_id, project_root, source = _resolve_project(api_base)
    return Config(api_base=api_base, project_id=project_id or "", project_root=project_root, source=source)


def get_available_projects() -> list[str]:
    """Fetch available project IDs from the API."""
    api_base = os.getenv("ST_API_BASE", DEFAULT_API_BASE)
    projects = _fetch_projects_with_retry(api_base, max_retries=2)
    if not projects:
        return []
    return [p.get("id") for p in projects if isinstance(p, dict) and p.get("id")]
