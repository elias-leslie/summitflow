"""Route handlers for project-scoped design standards endpoints."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..storage import design_standards as ds_storage
from .design_standards_models import (
    CreateRuleRequest,
    CreateStandardRequest,
    DesignRuleResponse,
    DesignStandardResponse,
    GenerateMockupRequest,
    MockupResponse,
    RulesByCategoryResponse,
    ValidationRequest,
    ValidationResponse,
    ViolationResponse,
)

router = APIRouter(tags=["design-standards"])


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


def _get_std_or_404(standard_id: int, project_id: str | None = None) -> dict[str, Any]:
    """Fetch a standard and raise 404 if missing or project mismatch."""
    std = ds_storage.get_standard_by_id(standard_id)
    if not std or (project_id and std["project_id"] and std["project_id"] != project_id):
        raise HTTPException(status_code=404, detail="Standard not found")
    return std


def _assert_not_base(std: dict[str, Any]) -> None:
    """Raise 400 if the standard is a base standard."""
    if std["is_base"] and std["project_id"] is None:
        raise HTTPException(
            status_code=400,
            detail="Cannot modify base standard rules via project endpoint",
        )


@router.get(
    "/projects/{project_id}/design-standards",
    response_model=list[DesignStandardResponse],
)
async def list_project_standards(project_id: str) -> list[DesignStandardResponse]:
    """List all design standards available to a project."""
    return [_standard_to_response(s) for s in ds_storage.list_standards(project_id)]


@router.post(
    "/projects/{project_id}/design-standards",
    response_model=DesignStandardResponse,
    status_code=201,
)
async def create_project_standard(
    project_id: str, request: CreateStandardRequest
) -> DesignStandardResponse:
    """Create a project-specific design standard."""
    if request.inherit_from_base:
        try:
            std = ds_storage.inherit_from_base(project_id, request.name)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    else:
        std = ds_storage.create_standard(
            name=request.name, description=request.description, project_id=project_id
        )
    return _standard_to_response(std)


# NOTE: These routes MUST come before /{standard_id} routes to avoid FastAPI matching
# "effective-rules" and "validate" as standard_id parameter


@router.get(
    "/projects/{project_id}/design-standards/effective-rules",
    response_model=list[DesignRuleResponse],
)
async def get_effective_rules(
    project_id: str,
    category: str | None = Query(None, description="Filter by category"),
) -> list[DesignRuleResponse]:
    """Get effective rules for a project (merged base + project, project overrides)."""
    return [
        _rule_to_response(r) for r in ds_storage.get_effective_rules(project_id, category)
    ]


@router.post(
    "/projects/{project_id}/design-standards/validate",
    response_model=ValidationResponse,
)
async def validate_element(
    project_id: str, request: ValidationRequest
) -> ValidationResponse:
    """Validate element data against project's design rules."""
    violations = ds_storage.validate_against_rules(
        project_id, request.element_data, request.category
    )
    return ValidationResponse(
        compliant=not violations,
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


@router.get(
    "/projects/{project_id}/design-standards/{standard_id}",
    response_model=DesignStandardResponse,
)
async def get_project_standard(project_id: str, standard_id: int) -> DesignStandardResponse:
    """Get a specific design standard by ID."""
    return _standard_to_response(_get_std_or_404(standard_id, project_id))


@router.delete("/projects/{project_id}/design-standards/{standard_id}")
async def delete_project_standard(project_id: str, standard_id: int) -> dict[str, Any]:
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
    _get_std_or_404(standard_id, project_id)
    return [_rule_to_response(r) for r in ds_storage.list_rules(standard_id, category)]


@router.get(
    "/projects/{project_id}/design-standards/{standard_id}/rules/by-category",
    response_model=RulesByCategoryResponse,
)
async def list_rules_by_category(project_id: str, standard_id: int) -> RulesByCategoryResponse:
    """List rules grouped by category."""
    _get_std_or_404(standard_id, project_id)
    rules_by_cat = ds_storage.list_rules_by_category(standard_id)
    return RulesByCategoryResponse(
        categories={cat: [_rule_to_response(r) for r in rules] for cat, rules in rules_by_cat.items()}
    )


@router.post(
    "/projects/{project_id}/design-standards/{standard_id}/rules",
    response_model=DesignRuleResponse,
    status_code=201,
)
async def create_rule(
    project_id: str, standard_id: int, request: CreateRuleRequest
) -> DesignRuleResponse:
    """Create a design rule within a standard."""
    std = _get_std_or_404(standard_id, project_id)
    _assert_not_base(std)
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
    project_id: str, standard_id: int, rule_id: str, request: CreateRuleRequest
) -> DesignRuleResponse:
    """Create or update a design rule."""
    std = _get_std_or_404(standard_id, project_id)
    _assert_not_base(std)
    rule = ds_storage.upsert_rule(
        standard_id=standard_id,
        category=request.category,
        rule_id=rule_id,
        name=request.name,
        requirements=request.requirements,
    )
    return _rule_to_response(rule)


@router.delete("/projects/{project_id}/design-standards/{standard_id}/rules/{rule_id}")
async def delete_rule(
    project_id: str, standard_id: int, rule_id: str
) -> dict[str, Any]:
    """Delete a design rule."""
    std = _get_std_or_404(standard_id, project_id)
    _assert_not_base(std)
    if not ds_storage.delete_rule(standard_id, rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"deleted": True, "rule_id": rule_id}


@router.post(
    "/projects/{project_id}/design-audit/generate-mockup",
    response_model=MockupResponse,
)
async def generate_mockup_endpoint(
    project_id: str, request: GenerateMockupRequest
) -> MockupResponse:
    """Generate a design mockup for an explorer entry (page)."""
    from ..services.mockup_generator import generate_mockup

    result = generate_mockup(
        project_id=project_id,
        explorer_entry_id=request.explorer_entry_id,
        standards_id=request.standards_id,
        design_direction=request.design_direction,
    )
    mockup_url = (
        f"/api/projects/{project_id}/mockups/{result.mockup_id}"
        if result.success and result.mockup_id
        else None
    )
    return MockupResponse(
        success=result.success,
        mockup_id=result.mockup_id,
        db_id=result.db_id,
        image_path=result.image_path,
        error=result.error,
        generator=result.generator,
        generation_time_ms=result.generation_time_ms,
        mockup_url=mockup_url,
    )
