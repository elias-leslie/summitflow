"""Task enrichment and review workflow input models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AutoFixInput(BaseModel):
    project_id: str
    check_type: Literal["pytest", "ruff", "types", "biome", "tsc"] | None = None
    limit: int = Field(default=10, ge=1, le=50)


class EnrichInput(BaseModel):
    project_id: str
    task_id: str
    raw_request: str


class ReviewPRInput(BaseModel):
    task_id: str
    pr_url: str | None = None
