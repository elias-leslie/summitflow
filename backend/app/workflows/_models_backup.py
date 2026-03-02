"""Backup and restore workflow input models."""

from __future__ import annotations

from pydantic import BaseModel

from ._model_constants import DEFAULT_BACKUP_TYPE


class BackupInput(BaseModel):
    project_id: str
    source_id: str | None = None
    note: str | None = None
    backup_type: str = DEFAULT_BACKUP_TYPE
    keep_local: bool = False
    retention_days: int | None = None


class RestoreInput(BaseModel):
    project_id: str
    source_id: str | None = None
    backup_id: str | None = None
    backup_file: str | None = None
    dry_run: bool = False
    db_only: bool = False
    files_only: bool = False
