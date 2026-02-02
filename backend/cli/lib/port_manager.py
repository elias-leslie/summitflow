"""Port management for worktree service isolation.

Provides port allocation for isolated worktree services to avoid
conflicts with main project services.

Port configuration is loaded from .st/services.yaml via project_config.
Default values (for SummitFlow-style projects):
    Main services:
        - Backend: 8001
        - Frontend: 3001
    Worktree services:
        - Backend: 8100 + (task_id_hash % range)
        - Frontend: 3100 + (task_id_hash % range)

Port assignments are persisted in ~/.local/share/st/worktrees/<project-id>/<task-id>/ports.json
"""

from __future__ import annotations

import hashlib
import json
import socket
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .project_config import load_services_config

if TYPE_CHECKING:
    from .project_config import ProjectServicesConfig

# Default port range (can be overridden by service config)
DEFAULT_PORT_RANGE = 100


@dataclass
class WorktreePorts:
    """Port assignments for a worktree's services."""

    task_id: str
    backend_port: int
    frontend_port: int
    api_url: str
    frontend_url: str

    def to_dict(self) -> dict[str, str | int]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, str | int]) -> WorktreePorts:
        """Create from dictionary."""
        return cls(**data)


def _get_task_hash(task_id: str) -> int:
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


def _get_port_offset(task_id: str, port_range: int = DEFAULT_PORT_RANGE) -> int:
    """Calculate port offset from task ID.

    Args:
        task_id: The task identifier.
        port_range: The port range size (default: DEFAULT_PORT_RANGE).

    Returns:
        Offset in range [0, port_range) to add to base ports.
    """
    return _get_task_hash(task_id) % port_range


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
    return _extract_ports_from_config(config)


def _extract_ports_from_config(config: ProjectServicesConfig) -> dict[str, dict[str, int]]:
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


def _get_ports_file(task_id: str) -> Path:
    """Get path to ports.json for a worktree.

    Args:
        task_id: The task identifier.

    Returns:
        Path to the ports.json file.
    """
    from .worktree import get_worktree_path

    return get_worktree_path(task_id) / "ports.json"


def get_worktree_ports(task_id: str) -> WorktreePorts | None:
    """Get existing port assignments for a worktree.

    Args:
        task_id: The task identifier.

    Returns:
        WorktreePorts if already allocated, None otherwise.
    """
    ports_file = _get_ports_file(task_id)
    if not ports_file.exists():
        return None

    try:
        data = json.loads(ports_file.read_text())
        return WorktreePorts.from_dict(data)
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def calculate_ports(
    task_id: str, project_root: str | Path | None = None
) -> tuple[int, int]:
    """Calculate deterministic ports for a task without persisting.

    Uses hash-based allocation from project service config:
        - Backend: worktree_port_base + (hash % range)
        - Frontend: worktree_port_base + (hash % range)

    Args:
        task_id: The task identifier.
        project_root: Root directory of the project. If None, uses cwd.

    Returns:
        Tuple of (backend_port, frontend_port).
    """
    ports_config = get_project_ports(project_root)

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
    offset = _get_port_offset(task_id, min_range)

    backend_port = backend_base + offset
    frontend_port = frontend_base + offset
    return backend_port, frontend_port


def allocate_ports(
    task_id: str, project_root: str | Path | None = None, force: bool = False
) -> WorktreePorts:
    """Allocate and persist port assignments for a worktree.

    Uses deterministic hash-based allocation by default.
    Falls back to sequential search if hash-based ports are unavailable.

    Args:
        task_id: The task identifier.
        project_root: Root directory of the project. If None, uses cwd.
        force: Force reallocation even if already assigned.

    Returns:
        WorktreePorts with assigned ports.

    Raises:
        RuntimeError: If no available ports found.
    """
    from .worktree import get_worktree_path

    # Check for existing allocation
    if not force:
        existing = get_worktree_ports(task_id)
        if existing:
            return existing

    # Calculate deterministic ports first
    backend_port, frontend_port = calculate_ports(task_id, project_root)

    # Check if hash-based ports are available
    backend_available = check_port_available(backend_port)
    frontend_available = check_port_available(frontend_port)

    if not (backend_available and frontend_available):
        # Fall back to sequential search for available ports
        backend_port, frontend_port = _find_available_ports(project_root)

    # Create ports object
    ports = WorktreePorts(
        task_id=task_id,
        backend_port=backend_port,
        frontend_port=frontend_port,
        api_url=f"http://localhost:{backend_port}",
        frontend_url=f"http://localhost:{frontend_port}",
    )

    # Persist to worktree directory
    worktree_path = get_worktree_path(task_id)
    if worktree_path.exists():
        ports_file = worktree_path / "ports.json"
        ports_file.write_text(json.dumps(ports.to_dict(), indent=2))

    return ports


def _find_available_ports(project_root: str | Path | None = None) -> tuple[int, int]:
    """Find available backend and frontend ports sequentially.

    Searches from base ports upward to find an available pair.

    Args:
        project_root: Root directory of the project. If None, uses cwd.

    Returns:
        Tuple of (backend_port, frontend_port).

    Raises:
        RuntimeError: If no available ports found in range.
    """
    ports_config = get_project_ports(project_root)

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


def release_ports(task_id: str) -> bool:
    """Release port assignments for a worktree.

    Called when a worktree is removed.

    Args:
        task_id: The task identifier.

    Returns:
        True if ports were released, False if no assignment existed.
    """
    ports_file = _get_ports_file(task_id)
    if ports_file.exists():
        ports_file.unlink()
        return True
    return False


def list_allocated_ports() -> list[WorktreePorts]:
    """List all currently allocated worktree ports.

    Returns:
        List of WorktreePorts for all worktrees with port assignments.
    """
    from .worktree import get_active_worktrees

    allocated = []
    for worktree in get_active_worktrees():
        ports = get_worktree_ports(worktree.task_id)
        if ports:
            allocated.append(ports)

    return allocated


def get_port_status(project_root: str | Path | None = None) -> dict[str, list[dict]]:
    """Get status of all port allocations.

    Args:
        project_root: Root directory of the project. If None, uses cwd.

    Returns:
        Dictionary with 'main' and 'worktrees' port information.
    """
    ports_config = get_project_ports(project_root)

    main_ports: list[dict] = []
    for service_name, cfg in ports_config.items():
        main_port = cfg.get("main", 0)
        if main_port:
            main_ports.append(
                {
                    "service": service_name,
                    "port": main_port,
                    "available": check_port_available(main_port),
                }
            )

    status: dict[str, list[dict]] = {
        "main": main_ports,
        "worktrees": [],
    }

    for ports in list_allocated_ports():
        status["worktrees"].append(
            {
                "task_id": ports.task_id,
                "backend_port": ports.backend_port,
                "backend_available": check_port_available(ports.backend_port),
                "frontend_port": ports.frontend_port,
                "frontend_available": check_port_available(ports.frontend_port),
            }
        )

    return status


def format_port_info(task_id: str, project_root: str | Path | None = None) -> str:
    """Format port information for display.

    Args:
        task_id: The task identifier.
        project_root: Root directory of the project. If None, uses cwd.

    Returns:
        Formatted string with port information.
    """
    ports = get_worktree_ports(task_id)
    if not ports:
        # Calculate what ports would be assigned
        backend_port, frontend_port = calculate_ports(task_id, project_root)
        return (
            f"Ports (not yet allocated):\n"
            f"  Backend:  {backend_port} (would be http://localhost:{backend_port})\n"
            f"  Frontend: {frontend_port} (would be http://localhost:{frontend_port})"
        )

    backend_status = "available" if check_port_available(ports.backend_port) else "in use"
    frontend_status = "available" if check_port_available(ports.frontend_port) else "in use"

    return (
        f"Ports for {task_id}:\n"
        f"  Backend:  {ports.backend_port} ({backend_status}) - {ports.api_url}\n"
        f"  Frontend: {ports.frontend_port} ({frontend_status}) - {ports.frontend_url}"
    )
