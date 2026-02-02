"""Port management for worktree service isolation.

Provides port allocation for isolated worktree services to avoid
conflicts with main SummitFlow services.

Main services:
    - Backend: 8001
    - Frontend: 3001

Worktree services:
    - Backend: 8100 + (task_id_hash % 100)
    - Frontend: 3100 + (task_id_hash % 100)

Port assignments are persisted in ~/.summitflow/worktrees/<task-id>/ports.json
"""

from __future__ import annotations

import hashlib
import json
import socket
from dataclasses import asdict, dataclass
from pathlib import Path

# Main service ports (never allocate these to worktrees)
MAIN_BACKEND_PORT = 8001
MAIN_FRONTEND_PORT = 3001

# Worktree port ranges
WORKTREE_BACKEND_BASE = 8100
WORKTREE_FRONTEND_BASE = 3100
PORT_RANGE = 100  # 8100-8199 for backend, 3100-3199 for frontend


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


def _get_port_offset(task_id: str) -> int:
    """Calculate port offset from task ID.

    Args:
        task_id: The task identifier.

    Returns:
        Offset in range [0, PORT_RANGE) to add to base ports.
    """
    return _get_task_hash(task_id) % PORT_RANGE


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


def calculate_ports(task_id: str) -> tuple[int, int]:
    """Calculate deterministic ports for a task without persisting.

    Uses hash-based allocation:
        - Backend: 8100 + (hash % 100)
        - Frontend: 3100 + (hash % 100)

    Args:
        task_id: The task identifier.

    Returns:
        Tuple of (backend_port, frontend_port).
    """
    offset = _get_port_offset(task_id)
    backend_port = WORKTREE_BACKEND_BASE + offset
    frontend_port = WORKTREE_FRONTEND_BASE + offset
    return backend_port, frontend_port


def allocate_ports(task_id: str, force: bool = False) -> WorktreePorts:
    """Allocate and persist port assignments for a worktree.

    Uses deterministic hash-based allocation by default.
    Falls back to sequential search if hash-based ports are unavailable.

    Args:
        task_id: The task identifier.
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
    backend_port, frontend_port = calculate_ports(task_id)

    # Check if hash-based ports are available
    backend_available = check_port_available(backend_port)
    frontend_available = check_port_available(frontend_port)

    if not (backend_available and frontend_available):
        # Fall back to sequential search for available ports
        backend_port, frontend_port = _find_available_ports()

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


def _find_available_ports() -> tuple[int, int]:
    """Find available backend and frontend ports sequentially.

    Searches from base ports upward to find an available pair.

    Returns:
        Tuple of (backend_port, frontend_port).

    Raises:
        RuntimeError: If no available ports found in range.
    """
    for offset in range(PORT_RANGE):
        backend_port = WORKTREE_BACKEND_BASE + offset
        frontend_port = WORKTREE_FRONTEND_BASE + offset

        if check_port_available(backend_port) and check_port_available(frontend_port):
            return backend_port, frontend_port

    raise RuntimeError(
        f"No available ports found in range "
        f"{WORKTREE_BACKEND_BASE}-{WORKTREE_BACKEND_BASE + PORT_RANGE - 1} (backend) / "
        f"{WORKTREE_FRONTEND_BASE}-{WORKTREE_FRONTEND_BASE + PORT_RANGE - 1} (frontend)"
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


def get_port_status() -> dict[str, list[dict]]:
    """Get status of all port allocations.

    Returns:
        Dictionary with 'main' and 'worktrees' port information.
    """
    status = {
        "main": [
            {
                "service": "backend",
                "port": MAIN_BACKEND_PORT,
                "available": check_port_available(MAIN_BACKEND_PORT),
            },
            {
                "service": "frontend",
                "port": MAIN_FRONTEND_PORT,
                "available": check_port_available(MAIN_FRONTEND_PORT),
            },
        ],
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


def format_port_info(task_id: str) -> str:
    """Format port information for display.

    Args:
        task_id: The task identifier.

    Returns:
        Formatted string with port information.
    """
    ports = get_worktree_ports(task_id)
    if not ports:
        # Calculate what ports would be assigned
        backend_port, frontend_port = calculate_ports(task_id)
        return (
            f"Ports (not yet allocated):\n"
            f"  Backend:  {backend_port} (would be {ports.api_url if ports else f'http://localhost:{backend_port}'})\n"
            f"  Frontend: {frontend_port} (would be {ports.frontend_url if ports else f'http://localhost:{frontend_port}'})"
        )

    backend_status = "available" if check_port_available(ports.backend_port) else "in use"
    frontend_status = "available" if check_port_available(ports.frontend_port) else "in use"

    return (
        f"Ports for {task_id}:\n"
        f"  Backend:  {ports.backend_port} ({backend_status}) - {ports.api_url}\n"
        f"  Frontend: {ports.frontend_port} ({frontend_status}) - {ports.frontend_url}"
    )
