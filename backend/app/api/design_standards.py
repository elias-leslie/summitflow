"""Design standards API endpoints.

Provides CRUD operations for UI/UX design standards and rules:
- Base standards: Global standards that projects can inherit from
- Project standards: Project-specific standards that extend base
- Design rules: Individual rules within standards organized by category

Public API: import ``router`` to mount all routes. All Pydantic models are
re-exported from this module for backwards-compatibility.
"""

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
from .design_standards_routes import router as _project_router

__all__ = [
    "CreateRuleRequest",
    "CreateStandardRequest",
    "DesignRuleResponse",
    "DesignStandardResponse",
    "GenerateMockupRequest",
    "MockupResponse",
    "RulesByCategoryResponse",
    "ValidationRequest",
    "ValidationResponse",
    "ViolationResponse",
    "router",
]

router = APIRouter(tags=["design-standards"])


@router.get("/design-standards/base", response_model=DesignStandardResponse)
async def get_base_standard() -> DesignStandardResponse:
    """Get the base (global) design standard.

    The base standard contains default UI/UX rules that all projects can inherit from.
    """
    std = ds_storage.get_base_standard()
    if not std:
        raise HTTPException(status_code=404, detail="No base standard exists")
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


@router.get("/design-standards/base/rules", response_model=list[DesignRuleResponse])
async def list_base_rules(
    category: str | None = Query(None, description="Filter by category"),
) -> list[DesignRuleResponse]:
    """List rules in the base standard."""
    std = ds_storage.get_base_standard()
    if not std:
        raise HTTPException(status_code=404, detail="No base standard exists")
    return [
        DesignRuleResponse(
            id=r["id"],
            standard_id=r["standard_id"],
            category=r["category"],
            rule_id=r["rule_id"],
            name=r["name"],
            requirements=r["requirements"],
            created_at=r["created_at"].isoformat() if r.get("created_at") else "",
            source=r.get("source"),
        )
        for r in ds_storage.list_rules(std["id"], category)
    ]


router.include_router(_project_router)
