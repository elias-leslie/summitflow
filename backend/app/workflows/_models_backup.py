"""Backup and restore workflow input models."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, model_validator

from ._model_constants import DEFAULT_BACKUP_TYPE


class BackupInput(BaseModel):
    project_id: str
    source_id: str | None = None
    note: str | None = None
    backup_type: str = DEFAULT_BACKUP_TYPE
    keep_local: bool = False
    retention_days: int | None = None

    @model_validator(mode="after")
    def default_source_id(self) -> Self:
        """Keep workflow concurrency and storage records source-scoped."""
        if self.source_id is None:
            self.source_id = self.project_id
        return self


class RestoreInput(BaseModel):
    project_id: str
    source_id: str | None = None
    backup_id: str | None = None
    backup_file: str | None = None
    dry_run: bool = False
    db_only: bool = False
    files_only: bool = False
