"""Shared Pydantic input/output models for Hatchet workflows."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, model_validator


class TaskInput(BaseModel):
    task_id: str
    project_id: str


class ProjectInput(BaseModel):
    """Project input for workflows, including cron-triggered ones.

    Hatchet cron triggers may pass None instead of {} as input.
    The model_validator ensures defaults apply in both cases.
    """

    project_id: str = "summitflow"

    @model_validator(mode="before")
    @classmethod
    def _handle_none_input(cls, data: Any) -> Any:
        if data is None:
            return {}
        return data


class EmptyInput(BaseModel):
    pass


class BackupInput(BaseModel):
    project_id: str
    source_id: str | None = None
    note: str | None = None
    backup_type: str = "manual"
    keep_local: bool = False
    retention_days: int | None = None


class RestoreInput(BaseModel):
    project_id: str
    backup_id: str | None = None
    backup_file: str | None = None
    dry_run: bool = False
    db_only: bool = False
    files_only: bool = False


class EnrichInput(BaseModel):
    project_id: str
    task_id: str
    raw_request: str


class ReviewPRInput(BaseModel):
    task_id: str
    pr_url: str | None = None


class ScanInput(BaseModel):
    project_id: str | None = None
    entry_type: str | None = None
    dry_run: bool = False


class StaleCleanupInput(BaseModel):
    max_age_days: int = 30


class DebugCleanupInput(BaseModel):
    max_age_days: int = 7
    max_files: int = 20


class MonitorInput(BaseModel):
    project_id: str = "summitflow"
    max_tasks: int = 10


class SystemdMonitorInput(BaseModel):
    project_id: str = "summitflow"
    since: str = "5 minutes ago"
    max_tasks: int = 10


class SelfHealingInput(BaseModel):
    max_errors: int = 20
    enabled: bool = True
