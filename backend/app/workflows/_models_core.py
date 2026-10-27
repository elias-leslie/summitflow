"""Core shared workflow input models."""

from __future__ import annotations

from pydantic import BaseModel


class EmptyInput(BaseModel):
    pass
