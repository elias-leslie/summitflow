"""Pydantic schemas for project service configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ServiceConfigSchema(BaseModel):
    """Schema for a single service configuration."""

    name: str = Field(..., description="Service identifier (e.g., 'backend', 'frontend')")
    command: str = Field(..., description="Command template with {port} placeholder")
    port: int = Field(..., description="Default port for the service")
    worktree_port_base: int = Field(..., description="Base port for worktree instances")
    worktree_port_range: int = Field(
        default=100, description="Number of ports available for worktrees"
    )
    cwd: str | None = Field(default=None, description="Working directory relative to project root")
    env_file: str | None = Field(
        default=None, description="Environment file to load (relative to cwd)"
    )
    build_command: str | None = Field(
        default=None, description="Optional build command to run before starting"
    )


class ProjectServicesResponse(BaseModel):
    """Response schema for project services configuration."""

    project_id: str = Field(..., description="Project identifier")
    services: dict[str, ServiceConfigSchema] = Field(
        ..., description="Map of service name to configuration"
    )
    config_source: str = Field(
        ...,
        description="Source of configuration: 'file' (.st/services.yaml) or 'default'",
    )
