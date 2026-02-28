"""Port management for worktree service isolation.

Port configuration is loaded from .st/services.yaml via project_config.
Port assignments are persisted in ~/.local/share/st/worktrees/<project-id>/<task-id>/ports.json
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .port_calculator import (
    calculate_ports_from_config,
    check_port_available,
    find_available_ports,
    get_project_ports,
)
from .port_persistence import delete_ports_file, load_ports_dict, save_ports_dict

# Constants
_URL_TEMPLATE = "http://localhost:{}"
_STATUS_AVAILABLE = "available"
_STATUS_IN_USE = "in use"


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
        return cls(
            task_id=str(data["task_id"]),
            backend_port=int(data["backend_port"]),
            frontend_port=int(data["frontend_port"]),
            api_url=str(data["api_url"]),
            frontend_url=str(data["frontend_url"]),
        )


def get_worktree_ports(task_id: str) -> WorktreePorts | None:
    """Get existing port assignments for a worktree."""
    data = load_ports_dict(task_id)
    if data is None:
        return None
    try:
        return WorktreePorts.from_dict(data)
    except (KeyError, TypeError):
        return None


def calculate_ports(task_id: str, project_root: str | Path | None = None) -> tuple[int, int]:
    """Calculate deterministic ports for a task without persisting."""
    return calculate_ports_from_config(task_id, get_project_ports(project_root))


def allocate_ports(
    task_id: str, project_root: str | Path | None = None, force: bool = False
) -> WorktreePorts:
    """Allocate and persist port assignments for a worktree.

    Uses deterministic hash-based allocation, falling back to sequential search.
    Raises RuntimeError if no available ports found.
    """
    if not force:
        existing = get_worktree_ports(task_id)
        if existing:
            return existing

    backend_port, frontend_port = calculate_ports(task_id, project_root)
    if not (check_port_available(backend_port) and check_port_available(frontend_port)):
        backend_port, frontend_port = find_available_ports(get_project_ports(project_root))

    ports = WorktreePorts(
        task_id=task_id,
        backend_port=backend_port,
        frontend_port=frontend_port,
        api_url=_URL_TEMPLATE.format(backend_port),
        frontend_url=_URL_TEMPLATE.format(frontend_port),
    )
    save_ports_dict(task_id, ports.to_dict())
    return ports


def release_ports(task_id: str) -> bool:
    """Release port assignments for a worktree."""
    return delete_ports_file(task_id)


def list_allocated_ports() -> list[WorktreePorts]:
    """List all currently allocated worktree ports."""
    from .worktree import get_active_worktrees

    return [p for w in get_active_worktrees() if (p := get_worktree_ports(w.task_id))]


def get_port_status(project_root: str | Path | None = None) -> dict[str, list[dict[str, str | int | bool]]]:
    """Get status of all port allocations."""
    ports_config = get_project_ports(project_root)
    main_ports: list[dict[str, str | int | bool]] = [
        {"service": name, "port": cfg["main"], "available": check_port_available(cfg["main"])}
        for name, cfg in ports_config.items()
        if cfg.get("main", 0)
    ]
    worktree_ports: list[dict[str, str | int | bool]] = [
        {
            "task_id": p.task_id,
            "backend_port": p.backend_port,
            "backend_available": check_port_available(p.backend_port),
            "frontend_port": p.frontend_port,
            "frontend_available": check_port_available(p.frontend_port),
        }
        for p in list_allocated_ports()
    ]
    return {"main": main_ports, "worktrees": worktree_ports}


def format_port_info(task_id: str, project_root: str | Path | None = None) -> str:
    """Format port information for display."""
    ports = get_worktree_ports(task_id)
    if not ports:
        b, f = calculate_ports(task_id, project_root)
        return (
            f"Ports (not yet allocated):\n"
            f"  Backend:  {b} (would be {_URL_TEMPLATE.format(b)})\n"
            f"  Frontend: {f} (would be {_URL_TEMPLATE.format(f)})"
        )
    b_status = _STATUS_AVAILABLE if check_port_available(ports.backend_port) else _STATUS_IN_USE
    f_status = _STATUS_AVAILABLE if check_port_available(ports.frontend_port) else _STATUS_IN_USE
    return (
        f"Ports for {task_id}:\n"
        f"  Backend:  {ports.backend_port} ({b_status}) - {ports.api_url}\n"
        f"  Frontend: {ports.frontend_port} ({f_status}) - {ports.frontend_url}"
    )
