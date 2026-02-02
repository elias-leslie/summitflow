"""Pydantic schemas for Ideas API."""

from __future__ import annotations

from pydantic import BaseModel


class IdeaCreate(BaseModel):
    """Request body for submitting an idea."""

    raw_text: str


class IdeaRetry(BaseModel):
    """Request body for retrying refinement."""

    additional_context: str | None = None
