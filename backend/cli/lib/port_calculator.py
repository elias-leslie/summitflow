"""Port calculation utilities for worktree service isolation.

Provides deterministic port calculation and availability checking.
"""

from __future__ import annotations

import hashlib
import socket
from pathlib import Path
from typing import TYPE_CHECKING

from .project_config import load_services_config

if TYPE_CHECKING:
    from .project_config import ProjectServicesConfig

# Default port range (can be overridden by service config)
DEFAULT_PORT_RANGE = 100


def get_task_hash(task_id: str) -> int:
    """Get a deterministic hash value from task ID.

    Args:
        task_id: The task identifier.

    Returns:
        Integer hash value for port offset calculation.
    """
    # Use MD5 for deterministic, fast hashing (not for security)
    hash_bytes = hashlib.md5(task_id.encode()).digest()
    # Use first 4 bytes as unsigned int
    return int.from_bytes(hash_bytes[:4], byteorder="big")


def get_port_offset(task_id: str, port_range: int = DEFAULT_PORT_RANGE) -> int:
    """Calculate port offset from task ID.

    Args:
        task_id: The task identifier.
        port_range: The port range size (default: DEFAULT_PORT_RANGE).

    Returns:
        Offset in range [0, port_range) to add to base ports.
    """
    return get_task_hash(task_id) % port_range


def extract_ports_from_config(config: ProjectServicesConfig) -> dict[str, dict[str, int]]:
    """Extract port information from a ProjectServicesConfig.

    Args:
        config: The project services configuration.

    Returns:
        Dictionary with port info for each service.
    """
    ports: dict[str, dict[str, int]] = {}

    for name, service in config.services.items():
        ports[name] = {
            "main": service.port,
            "worktree_base": service.worktree_port_base,
            "range": service.worktree_port_range,
        }

    return ports


def get_project_ports(project_root: str | Path | None = None) -> dict[str, dict[str, int]]:
    """Get port configuration from project service config.

    Args:
        project_root: Root directory of the project. If None, uses cwd.

    Returns:
        Dictionary with port info for each service:
        {
            "backend": {"main": 8001, "worktree_base": 8100, "range": 100},
            "frontend": {"main": 3001, "worktree_base": 3100, "range": 100},
        }
    """
    if project_root is None:
        project_root = Path.cwd()

    config = load_services_config(project_root)
    return extract_ports_from_config(config)


def check_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a port is available for binding.

    Args:
        port: Port number to check.
        host: Host address to check (default localhost).

    Returns:
        True if port is available, False if in use.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            # If connect fails (result != 0), port is available
            return result != 0
    except OSError:
        # Error usually means port is not usable
        return False


def calculate_ports_from_config(
    task_id: str, ports_config: dict[str, dict[str, int]]
) -> tuple[int, int]:
    """Calculate deterministic ports for a task from config.

    Args:
        task_id: The task identifier.
        ports_config: Port configuration dictionary.

    Returns:
        Tuple of (backend_port, frontend_port).
    """
    # Get backend config (with fallback defaults)
    backend_cfg = ports_config.get("backend", {})
    backend_base = backend_cfg.get("worktree_base", 8100)
    backend_range = backend_cfg.get("range", DEFAULT_PORT_RANGE)

    # Get frontend config (with fallback defaults)
    frontend_cfg = ports_config.get("frontend", {})
    frontend_base = frontend_cfg.get("worktree_base", 3100)
    frontend_range = frontend_cfg.get("range", DEFAULT_PORT_RANGE)

    # Use minimum range for offset calculation to ensure consistency
    min_range = min(backend_range, frontend_range)
    offset = get_port_offset(task_id, min_range)

    backend_port = backend_base + offset
    frontend_port = frontend_base + offset
    return backend_port, frontend_port


def find_available_ports(ports_config: dict[str, dict[str, int]]) -> tuple[int, int]:
    """Find available backend and frontend ports sequentially.

    Searches from base ports upward to find an available pair.

    Args:
        ports_config: Port configuration dictionary.

    Returns:
        Tuple of (backend_port, frontend_port).

    Raises:
        RuntimeError: If no available ports found in range.
    """
    # Get backend config (with fallback defaults)
    backend_cfg = ports_config.get("backend", {})
    backend_base = backend_cfg.get("worktree_base", 8100)
    backend_range = backend_cfg.get("range", DEFAULT_PORT_RANGE)

    # Get frontend config (with fallback defaults)
    frontend_cfg = ports_config.get("frontend", {})
    frontend_base = frontend_cfg.get("worktree_base", 3100)
    frontend_range = frontend_cfg.get("range", DEFAULT_PORT_RANGE)

    # Use minimum range for iteration
    min_range = min(backend_range, frontend_range)

    for offset in range(min_range):
        backend_port = backend_base + offset
        frontend_port = frontend_base + offset

        if check_port_available(backend_port) and check_port_available(frontend_port):
            return backend_port, frontend_port

    raise RuntimeError(
        f"No available ports found in range "
        f"{backend_base}-{backend_base + backend_range - 1} (backend) / "
        f"{frontend_base}-{frontend_base + frontend_range - 1} (frontend)"
    )
