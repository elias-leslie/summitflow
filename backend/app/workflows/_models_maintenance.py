"""Maintenance workflow input models (cleanup)."""

from __future__ import annotations

from pydantic import BaseModel


class StaleCleanupInput(BaseModel):
    max_age_days: int = 30
