"""Core acceptance criterion schema."""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AcceptanceCriterion(BaseModel):
    """Acceptance criterion for AI agent reliability.

    Each criterion must be specific, measurable, and verifiable.
    The id must match pattern ac-NNN... with 3 or more digits (e.g., ac-001, ac-0001).
    """

    id: str = Field(description="Unique ID in format ac-NNN... (3 or more digits)")
    criterion: str = Field(min_length=10, description="Specific measurable condition")
    category: Literal["performance", "correctness", "security", "quality"] = Field(
        default="correctness", description="Category of the criterion"
    )
    measurement: str = Field(
        default="test", description="How to verify: test, metric, tool, manual"
    )
    threshold: str | None = Field(
        default=None, description="Specific value or condition (e.g., '<200ms', '100%')"
    )
    test_file: str | None = Field(default=None, description="Test file path when agent writes test")
    test_name: str | None = Field(
        default=None, description="Test function name when agent writes test"
    )
    verified: bool = Field(default=False, description="Whether criterion has been verified")
    verified_at: datetime | None = Field(default=None, description="When criterion was verified")
    verified_by: Literal["opus", "test", "human", "agent"] | None = Field(
        default=None, description="Who verified the criterion"
    )

    @field_validator("id")
    @classmethod
    def validate_id_format(cls, v: str) -> str:
        """Validate that id matches pattern ac-NNN... (3 or more digits)."""
        if not re.match(r"^ac-\d{3,}$", v):
            raise ValueError("id must match pattern ac-NNN... with 3 or more digits (e.g., ac-001, ac-0001)")
        return v

    @field_validator("criterion")
    @classmethod
    def validate_criterion_not_vague(cls, v: str) -> str:
        """Basic validation that criterion is not too vague."""
        vague_patterns = ["is good", "works well", "is fast", "is efficient"]
        lower_v = v.lower()
        for pattern in vague_patterns:
            if pattern in lower_v and len(v) < 30:
                raise ValueError(f"Criterion too vague. Avoid patterns like '{pattern}'.")
        return v
