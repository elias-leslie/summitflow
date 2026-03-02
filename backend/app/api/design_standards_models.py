"""Pydantic models for design standards API endpoints."""

from typing import Any

from pydantic import BaseModel


class DesignStandardResponse(BaseModel):
    """Response model for a design standard."""

    id: int
    project_id: str | None
    name: str
    description: str | None
    base_standard_id: int | None
    is_base: bool
    created_at: str
    updated_at: str


class CreateStandardRequest(BaseModel):
    """Request to create a project standard."""

    name: str = "default"
    description: str | None = None
    inherit_from_base: bool = True


class DesignRuleResponse(BaseModel):
    """Response model for a design rule."""

    id: int
    standard_id: int
    category: str
    rule_id: str
    name: str
    requirements: dict[str, Any]
    created_at: str
    source: str | None = None


class CreateRuleRequest(BaseModel):
    """Request to create a design rule."""

    category: str
    rule_id: str
    name: str
    requirements: dict[str, Any]


class RulesByCategoryResponse(BaseModel):
    """Response with rules grouped by category."""

    categories: dict[str, list[DesignRuleResponse]]


class ValidationRequest(BaseModel):
    """Request to validate element against rules."""

    element_data: dict[str, Any]
    category: str | None = None


class ViolationResponse(BaseModel):
    """Response for a rule violation."""

    rule_id: str
    rule_name: str
    category: str
    requirement: str
    expected: str
    actual: Any
    severity: str


class ValidationResponse(BaseModel):
    """Response from validation."""

    compliant: bool
    violations: list[ViolationResponse]


class GenerateMockupRequest(BaseModel):
    """Request to generate a mockup for a page."""

    explorer_entry_id: int
    standards_id: str = "base"
    design_direction: str | None = None


class MockupResponse(BaseModel):
    """Response from mockup generation."""

    success: bool
    mockup_id: str | None = None
    db_id: int | None = None
    image_path: str | None = None
    error: str | None = None
    generator: str | None = None
    generation_time_ms: int = 0
    mockup_url: str | None = None
