"""Task enrichment and review workflow input models."""

from __future__ import annotations

from pydantic import BaseModel


class EnrichInput(BaseModel):
    project_id: str
    task_id: str
    raw_request: str


class ReviewPRInput(BaseModel):
    task_id: str
    pr_url: str | None = None
