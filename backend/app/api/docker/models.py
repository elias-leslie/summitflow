"""Pydantic models for the runtime management API."""

from __future__ import annotations

from datetime import datetime
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
    # systemd auto-start (UnitFileState): True=enabled, False=disabled,
    # None=not togglable (docker infra, or static/masked units).
    auto_start: bool | None = None


class RuntimeServiceMetrics(BaseModel):
    name: str
    service: str
    cpu_percent: str
    mem_usage: str
    mem_percent: str
    net_io: str
    block_io: str


class RuntimeMetricSample(BaseModel):
    sampled_at: datetime
    sample_count: int
    state: str | None
    status: str | None
    cpu_percent: float | None
    cpu_percent_max: float | None
    memory_percent: float | None
    memory_percent_max: float | None
    memory_used_bytes: int | None
    memory_used_bytes_max: int | None
    memory_limit_bytes: int | None
    raw_mem_usage: str | None
    net_io: str | None
    block_io: str | None


class RuntimeMetricSeries(BaseModel):
    service: str
    display_name: str
    manager: str
    category: str
    samples: list[RuntimeMetricSample]


class RuntimeMetricSummary(BaseModel):
    service: str
    display_name: str | None
    manager: str | None
    category: str | None
    sample_count: int
    cpu_percent_avg: float | None
    cpu_percent_max: float | None
    memory_percent_avg: float | None
    memory_percent_max: float | None
    memory_used_bytes_avg: int | None
    memory_used_bytes_max: int | None
    last_sampled_at: datetime | None
    state: str | None


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
