"""Monitoring and self-healing workflow input models."""

from __future__ import annotations

from pydantic import BaseModel

from ._model_constants import DEFAULT_PROJECT_ID, DEFAULT_SYSTEMD_SINCE


class MonitorInput(BaseModel):
    project_id: str = DEFAULT_PROJECT_ID
    max_tasks: int = 10


class SystemdMonitorInput(BaseModel):
    project_id: str = DEFAULT_PROJECT_ID
    since: str = DEFAULT_SYSTEMD_SINCE
    max_tasks: int = 10


class SelfHealingInput(BaseModel):
    max_errors: int = 20
    enabled: bool = True
