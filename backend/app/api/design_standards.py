"""Design standards API endpoints.

Provides CRUD operations for UI/UX design standards and rules:
- Base standards: Global standards that projects can inherit from
- Project standards: Project-specific standards that extend base
- Design rules: Individual rules within standards organized by category
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..storage import design_standards as ds_storage

router = APIRouter(tags=["design-standards"])


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


def _standard_to_response(std: dict[str, Any]) -> DesignStandardResponse:
    """Convert storage dict to response model."""
    return DesignStandardResponse(
        id=std["id"],
        project_id=std["project_id"],
        name=std["name"],
        description=std["description"],
        base_standard_id=std["base_standard_id"],
        is_base=std["is_base"],
        created_at=std["created_at"].isoformat() if std.get("created_at") else "",
        updated_at=std["updated_at"].isoformat() if std.get("updated_at") else "",
    )


def _rule_to_response(rule: dict[str, Any]) -> DesignRuleResponse:
    """Convert storage dict to response model."""
    return DesignRuleResponse(
        id=rule["id"],
        standard_id=rule["standard_id"],
        category=rule["category"],
        rule_id=rule["rule_id"],
        name=rule["name"],
        requirements=rule["requirements"],
        created_at=rule["created_at"].isoformat() if rule.get("created_at") else "",
        source=rule.get("source"),
    )


@router.get(
    "/design-standards/base",
    response_model=DesignStandardResponse,
)
async def get_base_standard() -> DesignStandardResponse:
    """Get the base (global) design standard.

    The base standard contains default UI/UX rules that all projects can inherit from.
    """
    std = ds_storage.get_base_standard()
    if not std:
        raise HTTPException(status_code=404, detail="No base standard exists")
    return _standard_to_response(std)


@router.get(
    "/design-standards/base/rules",
    response_model=list[DesignRuleResponse],
)
async def list_base_rules(
    category: str | None = Query(None, description="Filter by category"),
) -> list[DesignRuleResponse]:
    """List rules in the base standard."""
    std = ds_storage.get_base_standard()
    if not std:
        raise HTTPException(status_code=404, detail="No base standard exists")

    rules = ds_storage.list_rules(std["id"], category)
    return [_rule_to_response(r) for r in rules]


@router.get(
    "/projects/{project_id}/design-standards",
    response_model=list[DesignStandardResponse],
)
async def list_project_standards(project_id: str) -> list[DesignStandardResponse]:
    """List all design standards available to a project.

    Returns both base standards and project-specific standards.
    """
    standards = ds_storage.list_standards(project_id)
    return [_standard_to_response(s) for s in standards]


@router.post(
    "/projects/{project_id}/design-standards",
    response_model=DesignStandardResponse,
    status_code=201,
)
async def create_project_standard(
    project_id: str,
    request: CreateStandardRequest,
) -> DesignStandardResponse:
    """Create a project-specific design standard.

    If inherit_from_base is True, the standard will inherit from the base standard.
    Project rules can then override base rules.
    """
    if request.inherit_from_base:
        try:
            std = ds_storage.inherit_from_base(project_id, request.name)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    else:
        std = ds_storage.create_standard(
            name=request.name,
            description=request.description,
            project_id=project_id,
        )

    return _standard_to_response(std)


@router.get(
    "/projects/{project_id}/design-standards/{standard_id}",
    response_model=DesignStandardResponse,
)
async def get_project_standard(
    project_id: str,
    standard_id: int,
) -> DesignStandardResponse:
    """Get a specific design standard by ID."""
    std = ds_storage.get_standard_by_id(standard_id)
    if not std or (std["project_id"] and std["project_id"] != project_id):
        raise HTTPException(status_code=404, detail="Standard not found")
    return _standard_to_response(std)


@router.delete(
    "/projects/{project_id}/design-standards/{standard_id}",
)
async def delete_project_standard(
    project_id: str,
    standard_id: int,
) -> dict[str, Any]:
    """Delete a project-specific design standard."""
    std = ds_storage.get_standard_by_id(standard_id)
    if not std or std["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Standard not found")

    if std["is_base"]:
        raise HTTPException(status_code=400, detail="Cannot delete base standard")

    ds_storage.delete_standard(standard_id)
    return {"deleted": True, "standard_id": standard_id}


@router.get(
    "/projects/{project_id}/design-standards/{standard_id}/rules",
    response_model=list[DesignRuleResponse],
)
async def list_standard_rules(
    project_id: str,
    standard_id: int,
    category: str | None = Query(None, description="Filter by category"),
) -> list[DesignRuleResponse]:
    """List rules for a specific standard."""
    std = ds_storage.get_standard_by_id(standard_id)
    if not std or (std["project_id"] and std["project_id"] != project_id):
        raise HTTPException(status_code=404, detail="Standard not found")

    rules = ds_storage.list_rules(standard_id, category)
    return [_rule_to_response(r) for r in rules]


@router.get(
    "/projects/{project_id}/design-standards/{standard_id}/rules/by-category",
    response_model=RulesByCategoryResponse,
)
async def list_rules_by_category(
    project_id: str,
    standard_id: int,
) -> RulesByCategoryResponse:
    """List rules grouped by category."""
    std = ds_storage.get_standard_by_id(standard_id)
    if not std or (std["project_id"] and std["project_id"] != project_id):
        raise HTTPException(status_code=404, detail="Standard not found")

    rules_by_cat = ds_storage.list_rules_by_category(standard_id)
    return RulesByCategoryResponse(
        categories={
            cat: [_rule_to_response(r) for r in rules] for cat, rules in rules_by_cat.items()
        }
    )


@router.post(
    "/projects/{project_id}/design-standards/{standard_id}/rules",
    response_model=DesignRuleResponse,
    status_code=201,
)
async def create_rule(
    project_id: str,
    standard_id: int,
    request: CreateRuleRequest,
) -> DesignRuleResponse:
    """Create a design rule within a standard."""
    std = ds_storage.get_standard_by_id(standard_id)
    if not std or (std["project_id"] and std["project_id"] != project_id):
        raise HTTPException(status_code=404, detail="Standard not found")

    if std["is_base"] and std["project_id"] is None:
        raise HTTPException(
            status_code=400,
            detail="Cannot modify base standard rules via project endpoint",
        )

    rule = ds_storage.create_rule(
        standard_id=standard_id,
        category=request.category,
        rule_id=request.rule_id,
        name=request.name,
        requirements=request.requirements,
    )
    return _rule_to_response(rule)


@router.put(
    "/projects/{project_id}/design-standards/{standard_id}/rules/{rule_id}",
    response_model=DesignRuleResponse,
)
async def upsert_rule(
    project_id: str,
    standard_id: int,
    rule_id: str,
    request: CreateRuleRequest,
) -> DesignRuleResponse:
    """Create or update a design rule."""
    std = ds_storage.get_standard_by_id(standard_id)
    if not std or (std["project_id"] and std["project_id"] != project_id):
        raise HTTPException(status_code=404, detail="Standard not found")

    if std["is_base"] and std["project_id"] is None:
        raise HTTPException(
            status_code=400,
            detail="Cannot modify base standard rules via project endpoint",
        )

    rule = ds_storage.upsert_rule(
        standard_id=standard_id,
        category=request.category,
        rule_id=rule_id,
        name=request.name,
        requirements=request.requirements,
    )
    return _rule_to_response(rule)


@router.delete(
    "/projects/{project_id}/design-standards/{standard_id}/rules/{rule_id}",
)
async def delete_rule(
    project_id: str,
    standard_id: int,
    rule_id: str,
) -> dict[str, Any]:
    """Delete a design rule."""
    std = ds_storage.get_standard_by_id(standard_id)
    if not std or (std["project_id"] and std["project_id"] != project_id):
        raise HTTPException(status_code=404, detail="Standard not found")

    if std["is_base"] and std["project_id"] is None:
        raise HTTPException(
            status_code=400,
            detail="Cannot modify base standard rules via project endpoint",
        )

    deleted = ds_storage.delete_rule(standard_id, rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Rule not found")

    return {"deleted": True, "rule_id": rule_id}


@router.get(
    "/projects/{project_id}/design-standards/effective-rules",
    response_model=list[DesignRuleResponse],
)
async def get_effective_rules(
    project_id: str,
    category: str | None = Query(None, description="Filter by category"),
) -> list[DesignRuleResponse]:
    """Get effective rules for a project.

    Returns merged rules from base and project standards.
    Project rules override base rules with the same rule_id.
    """
    rules = ds_storage.get_effective_rules(project_id, category)
    return [_rule_to_response(r) for r in rules]


@router.post(
    "/projects/{project_id}/design-standards/validate",
    response_model=ValidationResponse,
)
async def validate_element(
    project_id: str,
    request: ValidationRequest,
) -> ValidationResponse:
    """Validate element data against project's design rules.

    Returns list of violations if any rules are not met.
    """
    violations = ds_storage.validate_against_rules(
        project_id,
        request.element_data,
        request.category,
    )

    return ValidationResponse(
        compliant=len(violations) == 0,
        violations=[
            ViolationResponse(
                rule_id=v["rule_id"],
                rule_name=v["rule_name"],
                category=v["category"],
                requirement=v["requirement"],
                expected=str(v["expected"]),
                actual=v["actual"],
                severity=v["severity"],
            )
            for v in violations
        ],
    )


# ============================================================================
# Design Audit / Mockup Generation
# ============================================================================


class GenerateMockupRequest(BaseModel):
    """Request to generate a mockup for a page."""

    explorer_entry_id: int
    standards_id: str = "base"
    design_direction: str | None = None


class MockupResponse(BaseModel):
    """Response from mockup generation."""

    success: bool
    evidence_id: str | None = None
    db_id: int | None = None
    image_path: str | None = None
    error: str | None = None
    generator: str | None = None
    generation_time_ms: int = 0
    mockup_url: str | None = None


@router.post(
    "/projects/{project_id}/design-audit/generate-mockup",
    response_model=MockupResponse,
)
async def generate_mockup_endpoint(
    project_id: str,
    request: GenerateMockupRequest,
) -> MockupResponse:
    """Generate a design mockup for an explorer entry (page).

    Uses Gemini 3 Pro Image for mockup generation with Claude HTML fallback.
    Mockups are stored as evidence with type='mockup' and status='pending_approval'.
    """
    from ..services.mockup_generator import generate_mockup

    result = generate_mockup(
        project_id=project_id,
        explorer_entry_id=request.explorer_entry_id,
        standards_id=request.standards_id,
        design_direction=request.design_direction,
    )

    mockup_url = None
    if result.success and result.evidence_id:
        mockup_url = f"/api/projects/{project_id}/evidence/{result.evidence_id}/screenshot"

    return MockupResponse(
        success=result.success,
        evidence_id=result.evidence_id,
        db_id=result.db_id,
        image_path=result.image_path,
        error=result.error,
        generator=result.generator,
        generation_time_ms=result.generation_time_ms,
        mockup_url=mockup_url,
    )
