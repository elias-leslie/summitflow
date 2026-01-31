"""Pydantic models for Explorer service.

Defines data structures for:
- ExplorerEntry: Unified entry type (file, table, task, endpoint)
- ExplorerStats: Aggregated statistics
- ScanResult: Scan operation results
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExplorerEntry(BaseModel):
    """A unified explorer entry (file, table, task, or endpoint)."""

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    project_id: str
    entry_type: str = Field(
        ..., pattern="^(file|table|task|endpoint|page|dependency|architecture)$"
    )
    path: str
    name: str
    health_status: str = Field(default="unknown", pattern="^(healthy|warning|error|unknown)$")
    metadata: dict[str, Any] = Field(default_factory=dict)
    last_scanned_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ExplorerEntryCreate(BaseModel):
    """Data required to create/update an explorer entry."""

    path: str
    name: str
    health_status: str = "unknown"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExplorerStats(BaseModel):
    """Aggregated statistics for explorer entries."""

    by_type: dict[str, int] = Field(default_factory=dict)
    by_health: dict[str, int] = Field(default_factory=dict)
    total: int = 0
    last_scanned: datetime | None = None


class ExplorerRelationship(BaseModel):
    """A relationship between two explorer entries."""

    id: int | None = None
    project_id: str
    source_type: str
    source_path: str
    target_type: str
    target_path: str
    relationship: str  # 'imports', 'calls', 'queries', 'references'
    created_at: datetime | None = None


class ScanResult(BaseModel):
    """Result of a scan operation."""

    success: bool
    entry_type: str
    entries_found: int = 0
    entries_saved: int = 0
    duration_ms: int = 0
    error: str | None = None


class ExplorerFilters(BaseModel):
    """Query filters for explorer entries."""

    type: str | None = None
    health: str | None = None
    path: str | None = None
    sort: str = "path"
    dir: str = "asc"
    limit: int = 1000
    offset: int = 0
