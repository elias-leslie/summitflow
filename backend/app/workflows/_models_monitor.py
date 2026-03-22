"""Self-healing workflow input models."""

from __future__ import annotations

from pydantic import BaseModel


class SelfHealingInput(BaseModel):
    max_errors: int = 20
    enabled: bool = True
