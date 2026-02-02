"""CLI configuration management."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


def get_agent_hub_url() -> str:
    """Get Agent Hub API URL.

    Uses AGENT_HUB_URL environment variable with fallback to localhost:8003.
    This is the single source of truth for Agent Hub URL in the CLI.
    """
    return os.getenv("AGENT_HUB_URL", "http://localhost:8003")


@dataclass(frozen=True)
class Config:
    """CLI configuration loaded from environment variables or auto-detected."""

    api_base: str
    project_id: str
    project_root: str | None = None  # Filesystem path to project root


# Module-level override (set by --project flag in main.py)
_project_override: str | None = None


def set_project_override(project_id: str | None) -> None:
    """Set project override from --project flag."""
    global _project_override
    _project_override = project_id
    # Clear cached config so next call picks up the override
    get_config.cache_clear()


def _detect_project_from_cwd(api_base: str, max_retries: int = 3) -> tuple[str | None, str | None]:
    """Detect project_id from current working directory.

    Queries the projects API and finds a project whose root_path
    contains or matches the current working directory.

    Args:
        api_base: API base URL to query projects from
        max_retries: Maximum number of retry attempts on transient failures

    Returns:
        Tuple of (project_id, root_path) or (None, None) if not found.
    """
    cwd = Path.cwd().resolve()

    for attempt in range(max_retries):
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{api_base}/projects")
                if response.status_code != 200:
                    logger.warning(
                        "Project detection: API returned %d (attempt %d/%d)",
                        response.status_code,
                        attempt + 1,
                        max_retries,
                    )
                    if attempt < max_retries - 1:
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    return None, None

                projects = response.json()
                if not isinstance(projects, list):
                    logger.warning("Project detection: API returned non-list response")
                    return None, None

                # Find project whose root_path contains or matches cwd
                for project in projects:
                    root_path = project.get("root_path")
                    if not root_path:
                        continue

                    root = Path(root_path).resolve()

                    # Check if cwd is within this project's root
                    try:
                        cwd.relative_to(root)
                        return project.get("id"), str(root)
                    except ValueError:
                        # cwd is not relative to this root
                        continue

                # No matching project found (not a transient error, don't retry)
                return None, None

        except httpx.TimeoutException as e:
            logger.warning(
                "Project detection timeout (attempt %d/%d): %s",
                attempt + 1,
                max_retries,
                e,
            )
            if attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))
                continue
        except httpx.RequestError as e:
            logger.warning(
                "Project detection network error (attempt %d/%d): %s",
                attempt + 1,
                max_retries,
                e,
            )
            if attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))
                continue
        except Exception as e:
            logger.error("Project detection unexpected error: %s", e)
            break

    return None, None


@lru_cache
def get_config() -> Config:
    """Get CLI configuration.

    Priority:
    1. --project flag (via _project_override)
    2. ST_PROJECT_ID environment variable
    3. Auto-detect from current working directory
    4. Error if none of the above work

    Returns:
        Config with api_base and project_id.

    Raises:
        SystemExit: If no project can be determined.
    """
    api_base = os.getenv("ST_API_BASE", "http://localhost:8001/api")

    # Priority 1: --project flag override
    if _project_override:
        return Config(
            api_base=api_base,
            project_id=_project_override,
            project_root=None,  # Could fetch from API if needed
        )

    # Priority 2: Environment variable
    env_project = os.getenv("ST_PROJECT_ID")
    if env_project:
        return Config(
            api_base=api_base,
            project_id=env_project,
            project_root=None,
        )

    # Priority 3: Auto-detect from cwd
    detected_id, detected_root = _detect_project_from_cwd(api_base)
    if detected_id:
        return Config(
            api_base=api_base,
            project_id=detected_id,
            project_root=detected_root,
        )

    # Priority 4: No project found - show helpful error
    import sys

    print(
        "Error: Could not determine project.\n"
        "\n"
        "Options:\n"
        "  1. Run from within a registered project directory\n"
        "  2. Set ST_PROJECT_ID environment variable\n"
        "  3. Use --project / -P flag: st -P myproject list\n"
        "\n"
        "List available projects: st projects",
        file=sys.stderr,
    )
    sys.exit(1)


def get_config_optional() -> Config:
    """Get CLI configuration without requiring a project.

    Same as get_config() but returns a Config with empty project_id
    instead of exiting if no project can be determined. Useful for
    commands that can operate without project context (e.g., global
    task lookups).

    Returns:
        Config with api_base always set; project_id may be empty string.
    """
    api_base = os.getenv("ST_API_BASE", "http://localhost:8001/api")

    # Priority 1: --project flag override
    if _project_override:
        return Config(
            api_base=api_base,
            project_id=_project_override,
            project_root=None,
        )

    # Priority 2: Environment variable
    env_project = os.getenv("ST_PROJECT_ID")
    if env_project:
        return Config(
            api_base=api_base,
            project_id=env_project,
            project_root=None,
        )

    # Priority 3: Auto-detect from cwd
    detected_id, detected_root = _detect_project_from_cwd(api_base)
    if detected_id:
        return Config(
            api_base=api_base,
            project_id=detected_id,
            project_root=detected_root,
        )

    # No project found - return minimal config
    return Config(
        api_base=api_base,
        project_id="",  # Empty string signals no project
        project_root=None,
    )
