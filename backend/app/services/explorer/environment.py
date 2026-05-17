"""Environment detection utilities for Explorer service.

Handles detection of Python/Node versions, package managers, and CLI commands
from project configuration files.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .base import get_project_root

# Filenames
PYPROJECT_TOML = "pyproject.toml"
PACKAGE_JSON = "package.json"
PNPM_LOCK = "pnpm-lock.yaml"
YARN_LOCK = "yarn.lock"
PACKAGE_LOCK_JSON = "package-lock.json"
VENV_DIR = ".venv"
BACKEND_DIR = "backend"
FRONTEND_DIR = "frontend"

# Regex patterns
REQUIRES_PYTHON_PATTERN = r'requires-python\s*=\s*["\']([^"\']+)["\']'
PROJECT_SCRIPTS_PATTERN = r"\[project\.scripts\](.*?)(?:\n\[|\Z)"

# Package manager names
PKG_MANAGER_PNPM = "pnpm"
PKG_MANAGER_YARN = "yarn"
PKG_MANAGER_NPM = "npm"

# Known project IDs
PROJECT_SUMMITFLOW = "summitflow"
PROJECT_AGENT_HUB = "agent-hub"

# Common commands per project
SUMMITFLOW_COMMON_COMMANDS = [
    "st claim <task-id>            # Claim task and create checkpoint",
    "st context <task-id>          # Show current task details",
    "st log <task-id> \"note\"       # Record progress on a claimed task",
    "st done <subtask-id> -t <task-id>  # Complete a subtask",
    "st done <task-id>             # Complete task (merge + cleanup)",
]

AGENT_HUB_COMMON_COMMANDS = [
    "st complete --agent <slug> <prompt>  # Route to agent",
    "st memory save <content>  # Save learning to memory",
    "st memory search <query>  # Semantic search",
]


def _read_python_info(pyproject_path: Path, root: Path) -> dict[str, Any]:
    """Extract Python version and venv info from a pyproject.toml path."""
    try:
        content = pyproject_path.read_text()
    except OSError:
        return {}

    info: dict[str, Any] = {}
    match = re.search(REQUIRES_PYTHON_PATTERN, content)
    if match:
        info["python_version"] = match.group(1)

    venv_path = pyproject_path.parent / VENV_DIR
    if venv_path.exists():
        info["venv_path"] = str(venv_path.relative_to(root))

    return info


def _detect_package_manager(root: Path) -> str:
    """Detect the Node package manager used in the project root."""
    if (root / PNPM_LOCK).exists():
        return PKG_MANAGER_PNPM
    if (root / YARN_LOCK).exists():
        return PKG_MANAGER_YARN
    return PKG_MANAGER_NPM


def _read_node_info(package_path: Path, root: Path) -> dict[str, Any]:
    """Extract Node version and package manager info from a package.json path."""
    try:
        content = json.loads(package_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}

    info: dict[str, Any] = {}
    engines = content.get("engines", {})
    if "node" in engines:
        info["node_version"] = engines["node"]

    package_manager = content.get("packageManager")
    if isinstance(package_manager, str) and package_manager:
        info["package_manager"] = package_manager.split("@", 1)[0]
    else:
        info["package_manager"] = _detect_package_manager(root)
    return info


def get_environment(project_id: str) -> dict[str, Any]:
    """Get environment info from pyproject.toml and package.json.

    Scans for Python version (requires-python) and Node version (engines.node).
    """
    root_path = get_project_root(project_id)
    if not root_path:
        return {}

    root = Path(root_path)
    env_info: dict[str, Any] = {}

    pyproject_paths = [root / PYPROJECT_TOML, root / BACKEND_DIR / PYPROJECT_TOML]
    for pyproject_path in pyproject_paths:
        if not pyproject_path.exists():
            continue
        python_info = _read_python_info(pyproject_path, root)
        if python_info:
            env_info.update(python_info)
            break

    package_paths = [root / PACKAGE_JSON, root / FRONTEND_DIR / PACKAGE_JSON]
    for package_path in package_paths:
        if not package_path.exists():
            continue
        node_info = _read_node_info(package_path, root)
        if node_info:
            env_info.update(node_info)
            break

    return env_info


def _parse_primary_command(content: str) -> dict[str, str]:
    """Parse [project.scripts] section and return primary CLI command info."""
    scripts_match = re.search(PROJECT_SCRIPTS_PATTERN, content, re.DOTALL)
    if not scripts_match:
        return {}

    scripts_section = scripts_match.group(1)
    for line in scripts_section.strip().split("\n"):
        if "=" not in line or line.strip().startswith("#"):
            continue
        parts = line.split("=", 1)
        cmd_name = parts[0].strip()
        if not cmd_name:
            continue
        return {
            "primary_command": cmd_name,
            "help_command": f"{cmd_name} --help",
        }

    return {}


def _read_cli_from_pyproject(pyproject_path: Path) -> dict[str, Any]:
    """Read CLI info from a single pyproject.toml file."""
    try:
        content = pyproject_path.read_text()
    except OSError:
        return {}

    return _parse_primary_command(content)


def _get_known_project_commands(project_id: str) -> list[str]:
    """Return common CLI commands for known project IDs."""
    if project_id == PROJECT_SUMMITFLOW:
        return SUMMITFLOW_COMMON_COMMANDS
    if project_id == PROJECT_AGENT_HUB:
        return AGENT_HUB_COMMON_COMMANDS
    return []


def get_cli_info(project_id: str) -> dict[str, Any]:
    """Get CLI command information from pyproject.toml.

    Parses [project.scripts] to find CLI entry points.
    """
    root_path = get_project_root(project_id)
    if not root_path:
        return {}

    root = Path(root_path)
    cli_info: dict[str, Any] = {}

    pyproject_paths = [root / PYPROJECT_TOML, root / BACKEND_DIR / PYPROJECT_TOML]
    for pyproject_path in pyproject_paths:
        if not pyproject_path.exists():
            continue
        parsed = _read_cli_from_pyproject(pyproject_path)
        if parsed:
            cli_info.update(parsed)
            break

    common_commands = _get_known_project_commands(project_id)
    if common_commands:
        cli_info["common_commands"] = common_commands

    return cli_info
