"""Application-neutral configuration and project resolution for ST extensions."""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import httpx
import yaml

from .execution_context import canonical_repo_root

logger = logging.getLogger(__name__)
_RETRY_DELAY = 0.5
_PROJECT_NOT_FOUND_MSG = (
    "No project for cwd. Run from a registered project tree, or pass -P <id>.\n"
    "Resolution: st projects (list known projects)"
)
_default_api_base = "http://localhost:8001/api"
_default_agent_hub_url = "http://localhost:8003"


@dataclass(frozen=True)
class Config:
    """ST API and selected-project configuration."""

    api_base: str
    project_id: str
    project_root: str | None = None
    source: str = "unknown"


@dataclass(frozen=True)
class _RuntimeConfig:
    api_base: str
    agent_hub_url: str
    project_id: str | None
    project_root: str | None
    cwd: str


_project_override: str | None = None
_runtime_config: _RuntimeConfig | None = None


def configure_defaults(*, api_base: str | None = None, agent_hub_url: str | None = None) -> None:
    """Set host defaults without introducing a dependency on the host application."""
    global _default_api_base, _default_agent_hub_url
    if api_base:
        _default_api_base = api_base
    if agent_hub_url:
        _default_agent_hub_url = agent_hub_url
    get_config.cache_clear()


def configure_runtime_context(
    *,
    api_base: str,
    agent_hub_url: str,
    project_id: str | None,
    project_root: str | None,
    cwd: str,
) -> None:
    """Install validated dispatcher context before owner callback resolution."""
    global _runtime_config
    _runtime_config = _RuntimeConfig(
        api_base=api_base,
        agent_hub_url=agent_hub_url,
        project_id=project_id,
        project_root=project_root,
        cwd=cwd,
    )
    get_config.cache_clear()


def clear_runtime_context() -> None:
    """Clear dispatcher-provided context, primarily for in-process callers and tests."""
    global _runtime_config
    _runtime_config = None
    get_config.cache_clear()


def _api_base() -> str:
    if _runtime_config is not None:
        return _runtime_config.api_base
    return os.getenv("ST_API_BASE", "").strip() or _default_api_base


def get_api_base() -> str:
    """Return the dispatcher, environment, or host-default ST API base URL."""
    return _api_base()


def get_agent_hub_url() -> str:
    """Return the dispatcher, environment, or host-default Agent Hub URL."""
    if _runtime_config is not None:
        return _runtime_config.agent_hub_url
    return os.getenv("AGENT_HUB_URL", "").strip() or _default_agent_hub_url


def set_project_override(project_id: str | None) -> None:
    """Set the direct-invocation project override and clear cached configuration."""
    global _project_override
    _project_override = project_id
    get_config.cache_clear()


def get_project_override() -> str | None:
    """Return a direct-invocation project override, if any."""
    return _project_override


def _resolve_project_from_list(projects: list[object], cwd: Path) -> tuple[str | None, str | None]:
    """Return the registered project containing cwd."""
    for project in projects:
        if not isinstance(project, dict):
            continue
        project_data = cast(dict[str, Any], project)
        root_path = project_data.get("root_path")
        if not root_path:
            continue
        root = Path(str(root_path)).resolve()
        try:
            cwd.relative_to(root)
            project_id = project_data.get("id")
            return (project_id if isinstance(project_id, str) else None), str(root)
        except ValueError:
            continue
    return None, None


def _read_project_id_from_index(root: Path) -> str | None:
    index_path = root / ".index.yaml"
    if not index_path.exists():
        return None
    try:
        data = yaml.safe_load(index_path.read_text())
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    project_id = data.get("project")
    if isinstance(project_id, str) and (project_id := project_id.strip()):
        return project_id
    return None


def _detect_project_from_local_metadata(cwd: Path) -> tuple[str | None, str | None]:
    candidates: list[Path] = []
    seen: set[Path] = set()
    canonical_root = canonical_repo_root(cwd)
    if canonical_root is not None:
        resolved_root = canonical_root.resolve()
        candidates.append(resolved_root)
        seen.add(resolved_root)
    for candidate in (cwd, *cwd.parents):
        resolved_candidate = candidate.resolve()
        if resolved_candidate in seen or not (resolved_candidate / ".index.yaml").exists():
            continue
        candidates.append(resolved_candidate)
        seen.add(resolved_candidate)
    for candidate in candidates:
        project_id = _read_project_id_from_index(candidate)
        if project_id:
            return project_id, str(candidate)
    return None, None


def _parse_projects_response(response: httpx.Response) -> list[object] | str | None:
    if response.status_code != 200:
        return f"status={response.status_code}"
    data = response.json()
    return data if isinstance(data, list) else None


def _fetch_projects_with_retry(api_base: str, max_retries: int) -> list[object] | None:
    for attempt in range(max_retries):
        try:
            response = httpx.get(f"{api_base}/projects", timeout=5.0)
        except httpx.TimeoutException as exc:
            logger.warning(
                "Project detection timeout (attempt %d/%d): %s", attempt + 1, max_retries, exc
            )
        except httpx.RequestError as exc:
            logger.warning(
                "Project detection network error (attempt %d/%d): %s",
                attempt + 1,
                max_retries,
                exc,
            )
        except Exception as exc:
            logger.error("Project detection unexpected error: %s", exc)
            return None
        else:
            result = _parse_projects_response(response)
            if isinstance(result, list):
                return result
            if result is None:
                logger.warning("Project detection: API returned non-list response")
                return None
            logger.warning(
                "Project detection: API returned %s (attempt %d/%d)",
                result,
                attempt + 1,
                max_retries,
            )
        if attempt < max_retries - 1:
            time.sleep(_RETRY_DELAY * (attempt + 1))
    return None


def _detect_project_from_cwd(
    api_base: str, max_retries: int = 3
) -> tuple[str | None, str | None]:
    try:
        cwd = Path.cwd().resolve()
    except OSError:
        return None, None
    project_id, root_path = _detect_project_from_local_metadata(cwd)
    if project_id:
        return project_id, root_path
    projects = _fetch_projects_with_retry(api_base, max_retries)
    if projects is None:
        return None, None
    project_id, root_path = _resolve_project_from_list(projects, cwd)
    if project_id:
        return project_id, root_path
    canonical_root = canonical_repo_root(cwd)
    if canonical_root and canonical_root != cwd:
        return _resolve_project_from_list(projects, canonical_root)
    return None, None


def _resolve_project(api_base: str) -> tuple[str | None, str | None, str]:
    if _runtime_config is not None:
        return _runtime_config.project_id, _runtime_config.project_root, "context"
    if _project_override:
        return _project_override, get_project_root_path(_project_override), "flag"
    env_project = os.getenv("ST_PROJECT_ID")
    if env_project:
        return env_project, None, "env"
    project_id, root_path = _detect_project_from_cwd(api_base)
    return project_id, root_path, "cwd"


@lru_cache
def get_config() -> Config:
    """Resolve configuration, exiting when a required project is unavailable."""
    api_base = _api_base()
    project_id, project_root, source = _resolve_project(api_base)
    if project_id:
        return Config(api_base, project_id, project_root, source)
    print(_PROJECT_NOT_FOUND_MSG, file=sys.stderr)
    raise SystemExit(1)


def get_config_optional() -> Config:
    """Resolve configuration without requiring project selection."""
    api_base = _api_base()
    project_id, project_root, source = _resolve_project(api_base)
    return Config(api_base, project_id or "", project_root, source)


def get_available_projects() -> list[str]:
    projects = _fetch_projects_with_retry(_api_base(), max_retries=2)
    if not projects:
        return []
    return [
        project_id
        for project in projects
        if isinstance(project, dict)
        and isinstance((project_id := cast(dict[str, Any], project).get("id")), str)
    ]


def get_project_root_path(project_id: str) -> str | None:
    projects = _fetch_projects_with_retry(_api_base(), max_retries=2)
    if not projects:
        return None
    for project in projects:
        if not isinstance(project, dict):
            continue
        project_data = cast(dict[str, Any], project)
        if project_data.get("id") == project_id:
            root_path = project_data.get("root_path")
            return str(root_path) if root_path else None
    return None
