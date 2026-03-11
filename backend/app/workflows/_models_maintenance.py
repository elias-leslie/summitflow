"""Maintenance workflow input models (scan, cleanup)."""

from __future__ import annotations

from pydantic import BaseModel


class ScanInput(BaseModel):
    project_id: str | None = None
    entry_type: str | None = None
    dry_run: bool = False


class StaleCleanupInput(BaseModel):
    max_age_days: int = 30
