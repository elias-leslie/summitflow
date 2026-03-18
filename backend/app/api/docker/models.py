"""Pydantic models for the runtime management API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class RuntimeServiceStatus(BaseModel):
    name: str
    service: str
    display_name: str
    manager: Literal["docker", "systemd"]
    category: Literal["app", "worker", "infra"]
    state: str
    health: str
    status: str
    ports: list[str]


class RuntimeServiceMetrics(BaseModel):
    name: str
    service: str
    cpu_percent: str
    mem_usage: str
    mem_percent: str
    net_io: str
    block_io: str


class HealthSummary(BaseModel):
    total: int
    healthy: int
    unhealthy: int
    running: int
    stopped: int


class ActionResult(BaseModel):
    success: bool
    message: str


class RuntimeModeStatus(BaseModel):
    runtime: Literal["docker", "docker-stopped", "native", "hybrid"]
    apps_runtime: Literal["docker", "native", "stopped"]
    infra_runtime: Literal["docker", "native", "stopped"]
    current_mode: Literal["dev", "prod"]
    configured_mode: Literal["dev", "prod"]
    default_mode: Literal["dev", "prod"]
    source: Literal["detected", "persisted", "default"]
    is_running: bool


class RuntimeModeUpdate(BaseModel):
    mode: Literal["dev", "prod"]
