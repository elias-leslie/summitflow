"""Project configuration loading from .st/services.yaml.

Provides dynamic service configuration per project, replacing hardcoded
port and command values. Supports loading from YAML files with sensible
defaults for SummitFlow-style projects.

Configuration file: .st/services.yaml
Example:
    services:
      backend:
        command: "uvicorn app.main:app --host 0.0.0.0 --port {port}"
        port: 8001
        worktree_port_base: 8100
        worktree_port_range: 100
        cwd: "backend"
        env_file: ".env"
      frontend:
        command: "npm run start -- --hostname 0.0.0.0 --port {port}"
        port: 3001
        worktree_port_base: 3100
        worktree_port_range: 100
        cwd: "frontend"
        build_command: "npm run build"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

import yaml

from app.config import SUMMITFLOW_BACKEND_PORT, SUMMITFLOW_FRONTEND_PORT


@dataclass
class ServiceConfig:
    """Configuration for a single service."""

    name: str
    command: str
    port: int
    worktree_port_base: int
    worktree_port_range: int = 100
    cwd: str | None = None
    env_file: str | None = None
    build_command: str | None = None

    def get_command(self, port: int | None = None) -> str:
        """Get the command with port substituted.

        Args:
            port: Port to use. Defaults to self.port.

        Returns:
            Command string with {port} replaced.
        """
        actual_port = port if port is not None else self.port
        return self.command.format(port=actual_port)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "command": self.command,
            "port": self.port,
            "worktree_port_base": self.worktree_port_base,
            "worktree_port_range": self.worktree_port_range,
            "cwd": self.cwd,
            "env_file": self.env_file,
            "build_command": self.build_command,
        }

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> ServiceConfig:
        """Create from dictionary.

        Args:
            name: Service name.
            data: Configuration dictionary.

        Returns:
            ServiceConfig instance.
        """
        return cls(
            name=name,
            command=data.get("command", ""),
            port=data.get("port", 0),
            worktree_port_base=data.get("worktree_port_base", 0),
            worktree_port_range=data.get("worktree_port_range", 100),
            cwd=data.get("cwd"),
            env_file=data.get("env_file"),
            build_command=data.get("build_command"),
        )


@dataclass
class ProjectServicesConfig:
    """Collection of service configurations for a project."""

    services: dict[str, ServiceConfig] = field(default_factory=dict)

    def get_service(self, name: str) -> ServiceConfig | None:
        """Get a service configuration by name.

        Args:
            name: Service name (e.g., 'backend', 'frontend').

        Returns:
            ServiceConfig if found, None otherwise.
        """
        return self.services.get(name)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {"services": {name: svc.to_dict() for name, svc in self.services.items()}}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectServicesConfig:
        """Create from dictionary.

        Args:
            data: Configuration dictionary with 'services' key.

        Returns:
            ProjectServicesConfig instance.
        """
        services_data = data.get("services", {})
        services = {
            name: ServiceConfig.from_dict(name, svc_data)
            for name, svc_data in services_data.items()
        }
        return cls(services=services)


# Default configurations for SummitFlow-style projects
DEFAULT_BACKEND_CONFIG = ServiceConfig(
    name="backend",
    command="uvicorn app.main:app --host 0.0.0.0 --port {port}",
    port=SUMMITFLOW_BACKEND_PORT,
    worktree_port_base=8100,
    worktree_port_range=100,
    cwd="backend",
    env_file=".env",
)

DEFAULT_FRONTEND_CONFIG = ServiceConfig(
    name="frontend",
    command="npm run start -- --hostname 0.0.0.0 --port {port}",
    port=SUMMITFLOW_FRONTEND_PORT,
    worktree_port_base=3100,
    worktree_port_range=100,
    cwd="frontend",
    build_command="npm run build",
)

DEFAULT_SERVICES_CONFIG = ProjectServicesConfig(
    services={
        "backend": DEFAULT_BACKEND_CONFIG,
        "frontend": DEFAULT_FRONTEND_CONFIG,
    }
)


def get_services_config_path(project_root: str | Path) -> Path:
    """Get the path to services.yaml for a project.

    Args:
        project_root: Root directory of the project.

    Returns:
        Path to .st/services.yaml file.
    """
    return Path(project_root) / ".st" / "services.yaml"


def load_services_config(project_root: str | Path) -> ProjectServicesConfig:
    """Load service configuration from .st/services.yaml.

    If the file doesn't exist, returns default configuration.

    Args:
        project_root: Root directory of the project.

    Returns:
        ProjectServicesConfig with loaded or default configuration.
    """
    config_path = get_services_config_path(project_root)

    if not config_path.exists():
        return DEFAULT_SERVICES_CONFIG

    try:
        with open(config_path) as f:
            data = yaml.safe_load(f)

        if data is None:
            return DEFAULT_SERVICES_CONFIG

        return ProjectServicesConfig.from_dict(data)
    except (yaml.YAMLError, OSError):
        # Return defaults on any error
        return DEFAULT_SERVICES_CONFIG


def save_services_config(project_root: str | Path, config: ProjectServicesConfig) -> None:
    """Save service configuration to .st/services.yaml.

    Creates the .st directory if it doesn't exist.

    Args:
        project_root: Root directory of the project.
        config: Configuration to save.
    """
    config_path = get_services_config_path(project_root)
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w") as f:
        yaml.dump(config.to_dict(), f, default_flow_style=False, sort_keys=False)
