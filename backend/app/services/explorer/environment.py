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


def get_environment(project_id: str) -> dict[str, Any]:
    """Get environment info from pyproject.toml and package.json.

    Scans for Python version (requires-python) and Node version (engines.node).
    """
    root_path = get_project_root(project_id)
    if not root_path:
        return {}

    root = Path(root_path)
    env_info: dict[str, Any] = {}

    # Check for Python project (pyproject.toml in root or backend/)
    pyproject_paths = [root / "pyproject.toml", root / "backend" / "pyproject.toml"]
    for pyproject_path in pyproject_paths:
        if pyproject_path.exists():
            try:
                content = pyproject_path.read_text()
                # Parse requires-python
                match = re.search(r'requires-python\s*=\s*["\']([^"\']+)["\']', content)
                if match:
                    env_info["python_version"] = match.group(1)
                # Check for venv
                venv_path = pyproject_path.parent / ".venv"
                if venv_path.exists():
                    env_info["venv_path"] = str(venv_path.relative_to(root))
                break
            except OSError:
                pass

    # Check for Node project (package.json in root or frontend/)
    package_paths = [root / "package.json", root / "frontend" / "package.json"]
    for package_path in package_paths:
        if package_path.exists():
            try:
                content = json.loads(package_path.read_text())
                # Check engines.node
                if "engines" in content and "node" in content["engines"]:
                    env_info["node_version"] = content["engines"]["node"]
                # Detect package manager
                if (root / "pnpm-lock.yaml").exists():
                    env_info["package_manager"] = "pnpm"
                elif (root / "yarn.lock").exists():
                    env_info["package_manager"] = "yarn"
                elif (root / "package-lock.json").exists() or package_path.exists():
                    env_info["package_manager"] = "npm"
                break
            except (OSError, json.JSONDecodeError):
                pass

    return env_info


def get_cli_info(project_id: str) -> dict[str, Any]:
    """Get CLI command information from pyproject.toml.

    Parses [project.scripts] to find CLI entry points.
    """
    root_path = get_project_root(project_id)
    if not root_path:
        return {}

    root = Path(root_path)
    cli_info: dict[str, Any] = {}

    # Check pyproject.toml for CLI scripts
    pyproject_paths = [root / "pyproject.toml", root / "backend" / "pyproject.toml"]
    for pyproject_path in pyproject_paths:
        if pyproject_path.exists():
            try:
                content = pyproject_path.read_text()
                # Find [project.scripts] section
                # Pattern: key = "module:func"
                scripts_match = re.search(
                    r"\[project\.scripts\](.*?)(?:\n\[|\Z)", content, re.DOTALL
                )
                if scripts_match:
                    scripts_section = scripts_match.group(1)
                    # Parse each script entry
                    for line in scripts_section.strip().split("\n"):
                        if "=" in line and not line.strip().startswith("#"):
                            parts = line.split("=", 1)
                            cmd_name = parts[0].strip()
                            if cmd_name:
                                cli_info["primary_command"] = cmd_name
                                cli_info["help_command"] = f"{cmd_name} --help"
                                break
                break
            except OSError:
                pass

    # Add common commands for known projects
    if project_id == "summitflow":
        cli_info["common_commands"] = [
            "st work <task-id>  # Set active task context",
            "st context         # Show current task details",
            "st step pass <subtask> <N>  # Mark step as passed",
            "st subtask pass    # Mark subtask as passed",
            "st done <task-id>  # Complete task (merge + cleanup)",
        ]
    elif project_id == "agent-hub":
        cli_info["common_commands"] = [
            "st complete --agent <slug> <prompt>  # Route to agent",
            "st memory save <content>  # Save learning to memory",
            "st memory search <query>  # Semantic search",
        ]

    return cli_info
