"""Runtime environment detection (Python/Node versions, package manager) for `.index.yaml`."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ._project import get_project_root

PYPROJECT_TOML = "pyproject.toml"
PACKAGE_JSON = "package.json"
VENV_DIR = ".venv"
BACKEND_DIR = "backend"
FRONTEND_DIR = "frontend"

REQUIRES_PYTHON_PATTERN = r'requires-python\s*=\s*["\']([^"\']+)["\']'

_LOCKFILE_PACKAGE_MANAGERS = (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"))


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
    for lockfile, manager in _LOCKFILE_PACKAGE_MANAGERS:
        if (root / lockfile).exists():
            return manager
    return "npm"


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
    """Get environment info from pyproject.toml (requires-python) and package.json (engines.node)."""
    root_path = get_project_root(project_id)
    if not root_path:
        return {}

    root = Path(root_path)
    env_info: dict[str, Any] = {}

    for pyproject_path in (root / PYPROJECT_TOML, root / BACKEND_DIR / PYPROJECT_TOML):
        if not pyproject_path.exists():
            continue
        python_info = _read_python_info(pyproject_path, root)
        if python_info:
            env_info.update(python_info)
            break

    for package_path in (root / PACKAGE_JSON, root / FRONTEND_DIR / PACKAGE_JSON):
        if not package_path.exists():
            continue
        node_info = _read_node_info(package_path, root)
        if node_info:
            env_info.update(node_info)
            break

    return env_info
