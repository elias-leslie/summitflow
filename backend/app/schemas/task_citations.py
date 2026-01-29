"""Task citation schemas for memory tracking."""

import re

from pydantic import BaseModel, Field, field_validator


class CitationLogRequest(BaseModel):
    """Request model for logging subtask citations.

    Citations use suffix notation for three-signal rating:
    - M:abc123+  -> mandate helpful (promote tier)
    - G:def456-  -> guardrail harmful (demote/blacklist)
    - M:xyz789   -> used/neutral (no suffix)

    Pattern: [MG]:[8-char uuid prefix][+/-]?
    """

    citations: list[str] = Field(
        ...,
        description="List of citations in suffix notation: M:abc123+, G:def456-, M:xyz789",
    )

    @field_validator("citations")
    @classmethod
    def validate_citations(cls, v: list[str]) -> list[str]:
        pattern = re.compile(r"^[MG]:[a-f0-9]{8}[+-]?$")
        for citation in v:
            if not pattern.match(citation):
                raise ValueError(
                    f"Invalid citation format: {citation}. "
                    "Expected format: M:abc12345+ or G:def67890- or M:xyz99999"
                )
        return v


class CitationLogResponse(BaseModel):
    """Response model for citation logging."""

    logged: int = Field(..., description="Number of citations logged")
    subtask_id: str = Field(..., description="Subtask ID citations were logged for")


class CitationAcknowledgeRequest(BaseModel):
    """Request model for acknowledging no citations needed.

    Requires explicit confirmation to create friction that makes
    the agent reflect before claiming no memories were helpful.
    """

    honestly_none: bool = Field(
        ...,
        description="Explicit confirmation: no injected memories helped with this subtask",
    )

    @field_validator("honestly_none")
    @classmethod
    def validate_honestly_none(cls, v: bool) -> bool:
        """Require true - false is invalid (just don't call the endpoint)."""
        if not v:
            raise ValueError(
                "honestly_none must be true. If memories helped, use POST /citations instead."
            )
        return v


class CitationAcknowledgeResponse(BaseModel):
    """Response model for acknowledging no citations needed."""

    acknowledged: bool = Field(..., description="Whether acknowledgment was recorded")
    subtask_id: str = Field(..., description="Subtask ID that was acknowledged")
