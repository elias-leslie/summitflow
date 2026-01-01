"""Capabilities API - CRUD for TDD capabilities."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..storage import capabilities as storage
from ..storage import criteria as criteria_storage
from ..storage import evidence as evidence_storage
from ..storage import explorer as explorer_storage
from ..storage import tests as tests_storage
from ..storage.connection import get_connection

router = APIRouter()


class CapabilityCreate(BaseModel):
    """Request model for creating a capability.

    component_id can be either:
    - int: Database ID of the component
    - str: Component slug (e.g., "backend-services") - will be resolved to ID
    """

    component_id: int | str
    capability_id: str
    name: str
    description: str | None = None
    priority: int = 2


class CapabilityUpdate(BaseModel):
    """Request model for updating a capability."""

    name: str | None = None
    description: str | None = None
    priority: int | None = None
    status: str | None = None


class CapabilityResponse(BaseModel):
    """Response model for a capability."""

    id: int
    project_id: str
    component_id: int
    capability_id: str
    name: str
    description: str | None = None
    priority: int
    status: str
    locked_at: str | None = None
    verification_url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ExplorerLinkCreate(BaseModel):
    """Request model for creating an explorer link."""

    explorer_entry_id: int
    link_type: str


class ExplorerLinkResponse(BaseModel):
    """Response model for an explorer link."""

    link_id: int
    link_type: str
    link_created_at: str | None = None
    entry: dict[str, Any]


class CapabilityWithTestsResponse(CapabilityResponse):
    """Response model for capability with linked tests."""

    tests: list[dict[str, Any]] = []
    criteria: list[dict[str, Any]] = []  # Linked acceptance criteria


class CreateCriterionRequest(BaseModel):
    """Request model for creating a criterion and linking to capability."""

    criterion: str = Field(min_length=10, description="Specific measurable condition")
    category: str = Field(
        default="correctness", description="performance, correctness, security, quality"
    )
    measurement: str = Field(default="test", description="test, metric, tool, manual")
    threshold: str | None = Field(default=None, description="Specific value e.g., '<200ms'")


class CriterionResponse(BaseModel):
    """Response model for an acceptance criterion."""

    id: int
    criterion_id: str
    criterion: str
    category: str
    measurement: str
    threshold: str | None = None
    created_at: str | None = None
    tests: list[dict[str, Any]] = []


class LinkTestRequest(BaseModel):
    """Request model for linking a test to a criterion."""

    test_id: int = Field(description="Database ID of the test to link")
    is_primary: bool = Field(default=False, description="Whether this is the primary test")


class UpdateCriterionRequest(BaseModel):
    """Request model for updating a criterion."""

    criterion: str | None = Field(default=None, min_length=10)
    category: str | None = Field(default=None)
    measurement: str | None = Field(default=None)
    threshold: str | None = Field(default=None)


@router.get("/{project_id}/capabilities", response_model=list[CapabilityResponse])
async def list_capabilities(
    project_id: str,
    component: int | None = Query(None, description="Filter by component database ID"),
) -> list[CapabilityResponse]:
    """List all capabilities for a project, optionally filtered by component."""
    capabilities_list = storage.list_capabilities(project_id, component_id=component)
    return [CapabilityResponse(**c) for c in capabilities_list]


@router.get(
    "/{project_id}/capabilities/{capability_id}", response_model=CapabilityWithTestsResponse
)
async def get_capability(project_id: str, capability_id: str) -> CapabilityWithTestsResponse:
    """Get a specific capability with linked tests and criteria."""
    capability = storage.get_capability(project_id, capability_id)
    if not capability:
        raise HTTPException(status_code=404, detail=f"Capability {capability_id} not found")

    # Get linked tests for this capability (via old capability_tests table)
    tests = tests_storage.get_tests_for_capability(project_id, capability["capability_id"])

    # Get linked criteria (new unified criteria)
    with get_connection() as conn:
        criteria = criteria_storage.get_criteria_for_capability(conn, project_id, capability_id)
        # Enrich each criterion with its linked tests
        for crit in criteria:
            crit["tests"] = criteria_storage.get_tests_for_criterion(conn, crit["id"])
            crit["created_at"] = crit["created_at"].isoformat() if crit.get("created_at") else None

    return CapabilityWithTestsResponse(**capability, tests=tests, criteria=criteria)


def _resolve_component_id(project_id: str, component_id: int | str) -> int:
    """Resolve component_id to database ID.

    If component_id is already an int, return it directly.
    If it's a string, look up the component by its slug.

    Raises:
        HTTPException: If component not found
    """
    if isinstance(component_id, int):
        return component_id

    # Look up by slug
    from ..storage import components as comp_storage

    component = comp_storage.get_component(project_id, component_id)
    if not component:
        raise HTTPException(
            status_code=400,
            detail=f"Component '{component_id}' not found. Use component slug or database ID.",
        )
    return int(component["id"])


@router.post("/{project_id}/capabilities", response_model=CapabilityResponse)
async def create_capability(project_id: str, body: CapabilityCreate) -> CapabilityResponse:
    """Create a new capability.

    component_id can be either the database ID (int) or the component slug (str).
    """
    # Resolve component_id to database ID if string
    resolved_component_id = _resolve_component_id(project_id, body.component_id)

    try:
        capability = storage.create_capability(
            project_id=project_id,
            component_id=resolved_component_id,
            capability_id=body.capability_id,
            name=body.name,
            description=body.description,
            priority=body.priority,
        )
        return CapabilityResponse(**capability)
    except Exception as e:
        if "duplicate key" in str(e).lower() or "unique constraint" in str(e).lower():
            raise HTTPException(
                status_code=409,
                detail=f"Capability {body.capability_id} already exists",
            ) from e
        if "violates foreign key constraint" in str(e).lower():
            raise HTTPException(
                status_code=400,
                detail=f"Component with id {resolved_component_id} not found",
            ) from e
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.patch("/{project_id}/capabilities/{capability_id}", response_model=CapabilityResponse)
async def update_capability(
    project_id: str, capability_id: str, body: CapabilityUpdate
) -> CapabilityResponse:
    """Update a capability."""
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    capability = storage.update_capability(project_id, capability_id, **updates)
    if not capability:
        raise HTTPException(status_code=404, detail=f"Capability {capability_id} not found")

    return CapabilityResponse(**capability)


@router.post("/{project_id}/capabilities/{capability_id}/lock", response_model=CapabilityResponse)
async def lock_capability(project_id: str, capability_id: str) -> CapabilityResponse:
    """Lock a capability (mark as verified/frozen)."""
    capability = storage.lock_capability(project_id, capability_id)
    if not capability:
        raise HTTPException(status_code=404, detail=f"Capability {capability_id} not found")

    return CapabilityResponse(**capability)


@router.post("/{project_id}/capabilities/{capability_id}/unlock", response_model=CapabilityResponse)
async def unlock_capability(project_id: str, capability_id: str) -> CapabilityResponse:
    """Unlock a capability."""
    capability = storage.unlock_capability(project_id, capability_id)
    if not capability:
        raise HTTPException(status_code=404, detail=f"Capability {capability_id} not found")

    return CapabilityResponse(**capability)


@router.delete("/{project_id}/capabilities/{capability_id}")
async def delete_capability(project_id: str, capability_id: str) -> dict[str, str]:
    """Delete a capability."""
    deleted = storage.delete_capability(project_id, capability_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Capability {capability_id} not found")

    return {"status": "deleted", "capability_id": capability_id}


class CriterionVerifyResult(BaseModel):
    """Verification result for a single criterion."""

    criterion_id: str
    criterion: str
    passed: bool
    tests: list[dict[str, Any]] = []


class VerifyResultV2(BaseModel):
    """Response model for capability verification with criteria details."""

    capability_id: str
    capability_status: str
    criteria_total: int
    criteria_passed: int
    criteria_details: list[CriterionVerifyResult]
    evidence_captured: bool
    evidence_count: int = 0  # Total evidence count across all criteria


@router.post("/{project_id}/capabilities/{capability_id}/verify", response_model=VerifyResultV2)
async def verify_capability(project_id: str, capability_id: str) -> VerifyResultV2:
    """Verify a capability by checking its linked criteria and tests.

    Returns per-criterion pass/fail status with test details.
    A criterion passes if at least one linked test has last_result='passed'.
    """
    capability = storage.get_capability(project_id, capability_id)
    if not capability:
        raise HTTPException(status_code=404, detail=f"Capability {capability_id} not found")

    criteria_details: list[CriterionVerifyResult] = []
    criteria_passed = 0

    with get_connection() as conn:
        # Get all criteria for this capability
        criteria = criteria_storage.get_criteria_for_capability(conn, project_id, capability_id)

        for crit in criteria:
            # Get tests for this criterion
            tests = criteria_storage.get_tests_for_criterion(conn, crit["id"])

            # Check if any test passed
            passed = any(t.get("last_result") == "passed" for t in tests)
            if passed:
                criteria_passed += 1

            # Convert test data for response
            test_details = [
                {
                    "test_id": t["test_id"],
                    "name": t["name"],
                    "last_result": t.get("last_result"),
                    "is_primary": t.get("is_primary", False),
                }
                for t in tests
            ]

            criteria_details.append(
                CriterionVerifyResult(
                    criterion_id=crit["criterion_id"],
                    criterion=crit["criterion"],
                    passed=passed,
                    tests=test_details,
                )
            )

    # Get latest capability status (computed status based on criteria/tests)
    capability = storage.get_capability(project_id, capability_id)

    # Get evidence counts for all criteria
    criterion_db_ids = [crit["id"] for crit in criteria if crit.get("id")]
    evidence_counts = evidence_storage.get_evidence_count_for_criteria(project_id, criterion_db_ids)
    total_evidence = sum(evidence_counts.values())
    evidence_captured = total_evidence > 0

    return VerifyResultV2(
        capability_id=capability_id,
        capability_status=capability["status"] if capability else "pending",
        criteria_total=len(criteria_details),
        criteria_passed=criteria_passed,
        criteria_details=criteria_details,
        evidence_captured=evidence_captured,
        evidence_count=total_evidence,
    )


# --- Explorer Link Endpoints ---


@router.post(
    "/{project_id}/capabilities/{capability_id}/explorer-links",
    response_model=dict[str, Any],
)
async def create_explorer_link(
    project_id: str, capability_id: str, body: ExplorerLinkCreate
) -> dict[str, Any]:
    """Create a link between a capability and an explorer entry."""
    # Verify capability exists
    capability = storage.get_capability(project_id, capability_id)
    if not capability:
        raise HTTPException(status_code=404, detail=f"Capability {capability_id} not found")

    try:
        link_id = explorer_storage.create_capability_link(
            project_id=project_id,
            explorer_entry_id=body.explorer_entry_id,
            capability_id=capability["id"],
            link_type=body.link_type,
        )
        return {"link_id": link_id, "status": "created"}
    except Exception as e:
        if "duplicate key" in str(e).lower() or "unique constraint" in str(e).lower():
            raise HTTPException(
                status_code=409,
                detail="Link already exists",
            ) from e
        if "violates foreign key constraint" in str(e).lower():
            raise HTTPException(
                status_code=400,
                detail=f"Explorer entry {body.explorer_entry_id} not found",
            ) from e
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/{project_id}/capabilities/{capability_id}/explorer-links/{link_id}")
async def delete_explorer_link(project_id: str, capability_id: str, link_id: int) -> dict[str, Any]:
    """Delete a link between a capability and an explorer entry."""
    deleted = explorer_storage.delete_capability_link(link_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Link {link_id} not found")

    return {"status": "deleted", "link_id": link_id}


@router.get(
    "/{project_id}/capabilities/{capability_id}/explorer-entries",
    response_model=list[ExplorerLinkResponse],
)
async def get_capability_explorer_entries(
    project_id: str, capability_id: str
) -> list[ExplorerLinkResponse]:
    """Get all explorer entries linked to a capability."""
    # Verify capability exists
    capability = storage.get_capability(project_id, capability_id)
    if not capability:
        raise HTTPException(status_code=404, detail=f"Capability {capability_id} not found")

    links = explorer_storage.get_capability_links(capability["id"])
    return [ExplorerLinkResponse(**link) for link in links]


# --- Criteria Endpoints ---


@router.post(
    "/{project_id}/capabilities/{capability_id}/criteria",
    response_model=CriterionResponse,
)
async def create_capability_criterion(
    project_id: str, capability_id: str, body: CreateCriterionRequest
) -> CriterionResponse:
    """Create a new criterion and link it to a capability."""
    capability = storage.get_capability(project_id, capability_id)
    if not capability:
        raise HTTPException(status_code=404, detail=f"Capability {capability_id} not found")

    with get_connection() as conn:
        # Create the criterion
        criterion = criteria_storage.create_criterion(
            conn,
            project_id,
            body.criterion,
            category=body.category,
            measurement=body.measurement,
            threshold=body.threshold,
        )

        # Link to capability
        criteria_storage.link_criterion_to_capability(conn, capability["id"], criterion["id"])

        return CriterionResponse(
            id=criterion["id"],
            criterion_id=criterion["criterion_id"],
            criterion=criterion["criterion"],
            category=criterion["category"],
            measurement=criterion["measurement"],
            threshold=criterion["threshold"],
            created_at=criterion["created_at"].isoformat() if criterion.get("created_at") else None,
            tests=[],
        )


@router.delete("/{project_id}/capabilities/{capability_id}/criteria/{criterion_id}")
async def delete_capability_criterion(
    project_id: str, capability_id: str, criterion_id: str
) -> dict[str, Any]:
    """Unlink and delete a criterion from a capability.

    The criterion is deleted if it becomes orphaned (no other links).
    """
    capability = storage.get_capability(project_id, capability_id)
    if not capability:
        raise HTTPException(status_code=404, detail=f"Capability {capability_id} not found")

    with get_connection() as conn:
        # Find criterion by criterion_id string
        criterion = criteria_storage.get_criterion(conn, project_id, criterion_id)
        if not criterion:
            raise HTTPException(status_code=404, detail=f"Criterion {criterion_id} not found")

        # Unlink (this handles orphan cleanup)
        unlinked = criteria_storage.unlink_criterion_from_capability(
            conn, capability["id"], criterion["id"]
        )
        if not unlinked:
            raise HTTPException(status_code=404, detail="Criterion not linked to capability")

    return {"status": "deleted", "criterion_id": criterion_id}


@router.post(
    "/{project_id}/capabilities/{capability_id}/criteria/{criterion_id}/link-test",
    response_model=dict[str, Any],
)
async def link_test_to_criterion(
    project_id: str, capability_id: str, criterion_id: str, body: LinkTestRequest
) -> dict[str, Any]:
    """Link an existing test to a criterion."""
    capability = storage.get_capability(project_id, capability_id)
    if not capability:
        raise HTTPException(status_code=404, detail=f"Capability {capability_id} not found")

    with get_connection() as conn:
        criterion = criteria_storage.get_criterion(conn, project_id, criterion_id)
        if not criterion:
            raise HTTPException(status_code=404, detail=f"Criterion {criterion_id} not found")

        linked = criteria_storage.link_test_to_criterion(
            conn, criterion["id"], body.test_id, is_primary=body.is_primary
        )
        if not linked:
            raise HTTPException(status_code=400, detail="Failed to link test")

    return {"status": "linked", "criterion_id": criterion_id, "test_id": body.test_id}


@router.patch("/{project_id}/criteria/{criterion_id}", response_model=CriterionResponse)
async def update_criterion(
    project_id: str, criterion_id: str, body: UpdateCriterionRequest
) -> CriterionResponse:
    """Update a criterion's fields.

    Supports updating: criterion text, category, measurement, threshold.
    """
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    with get_connection() as conn:
        # Find and update criterion
        updated = criteria_storage.update_criterion(conn, project_id, criterion_id, updates)
        if not updated:
            raise HTTPException(status_code=404, detail=f"Criterion {criterion_id} not found")

        # Get linked tests for response
        tests = criteria_storage.get_tests_for_criterion(conn, updated["id"])

        return CriterionResponse(
            id=updated["id"],
            criterion_id=updated["criterion_id"],
            criterion=updated["criterion"],
            category=updated["category"],
            measurement=updated["measurement"],
            threshold=updated["threshold"],
            created_at=updated["created_at"].isoformat() if updated.get("created_at") else None,
            tests=tests,
        )


@router.delete("/{project_id}/criteria/{criterion_id}/test/{test_id}")
async def unlink_test_from_criterion(
    project_id: str, criterion_id: str, test_id: int
) -> dict[str, Any]:
    """Unlink a test from a criterion."""
    with get_connection() as conn:
        criterion = criteria_storage.get_criterion(conn, project_id, criterion_id)
        if not criterion:
            raise HTTPException(status_code=404, detail=f"Criterion {criterion_id} not found")

        unlinked = criteria_storage.unlink_test_from_criterion(conn, criterion["id"], test_id)
        if not unlinked:
            raise HTTPException(status_code=404, detail="Test not linked to criterion")

    return {"status": "unlinked", "criterion_id": criterion_id, "test_id": test_id}


# =============================================================================
# Batch Endpoints
# =============================================================================


class BatchCriterionCreate(BaseModel):
    """Criterion to create and link to capability during batch creation."""

    criterion: str = Field(min_length=10, description="Specific measurable condition")
    category: str = Field(
        default="correctness", description="performance, correctness, security, quality"
    )
    measurement: str = Field(default="test", description="test, metric, tool, manual")
    threshold: str | None = Field(default=None, description="Specific value e.g., '<200ms'")


class BatchCapabilityCreate(BaseModel):
    """Request model for a single capability in batch creation.

    component_id can be either:
    - int: Database ID of the component
    - str: Component slug (e.g., "backend-services") - will be resolved to ID
    """

    component_id: int | str
    capability_id: str
    name: str
    description: str | None = None
    priority: int = 2
    criteria: list[BatchCriterionCreate] = Field(default_factory=list)


class BatchCapabilityRequest(BaseModel):
    """Request model for batch capability creation."""

    items: list[BatchCapabilityCreate]


class BatchCapabilityResult(BaseModel):
    """Result for a single item in batch create."""

    capability_id: str
    success: bool
    id: int | None = None
    criteria_created: int = 0
    error: str | None = None


class BatchCapabilityResponse(BaseModel):
    """Response model for batch capability creation."""

    created: list[CapabilityResponse]
    errors: list[BatchCapabilityResult]


@router.post("/{project_id}/capabilities/batch", response_model=BatchCapabilityResponse)
async def batch_create_capabilities(
    project_id: str, body: BatchCapabilityRequest
) -> BatchCapabilityResponse:
    """Create multiple capabilities in a single request.

    Each capability can optionally include nested criteria that will be
    created and linked automatically.

    Handles partial failures: returns both created capabilities and errors.
    Each capability is created independently, so failures don't rollback successes.

    Args:
        project_id: Project ID
        body: List of capabilities to create (with optional nested criteria)

    Returns:
        BatchCapabilityResponse with created capabilities and any errors.
    """
    created: list[CapabilityResponse] = []
    errors: list[BatchCapabilityResult] = []

    for item in body.items:
        try:
            # Resolve component_id to database ID if string
            try:
                resolved_component_id = _resolve_component_id(project_id, item.component_id)
            except HTTPException as e:
                errors.append(
                    BatchCapabilityResult(
                        capability_id=item.capability_id,
                        success=False,
                        error=e.detail,
                    )
                )
                continue

            # Create the capability
            capability = storage.create_capability(
                project_id=project_id,
                component_id=resolved_component_id,
                capability_id=item.capability_id,
                name=item.name,
                description=item.description,
                priority=item.priority,
            )

            # Create and link criteria if provided
            criteria_count = 0
            if item.criteria:
                with get_connection() as conn:
                    for crit in item.criteria:
                        criterion = criteria_storage.create_criterion(
                            conn=conn,
                            project_id=project_id,
                            criterion=crit.criterion,
                            category=crit.category,
                            measurement=crit.measurement,
                            threshold=crit.threshold,
                        )
                        criteria_storage.link_criterion_to_capability(
                            conn, capability["id"], criterion["id"]
                        )
                        criteria_count += 1

            created.append(CapabilityResponse(**capability))
        except Exception as e:
            error_msg = str(e)
            if "duplicate key" in error_msg.lower() or "unique constraint" in error_msg.lower():
                error_msg = f"Capability {item.capability_id} already exists"
            elif "violates foreign key constraint" in error_msg.lower():
                error_msg = f"Component with id {resolved_component_id} not found"
            errors.append(
                BatchCapabilityResult(
                    capability_id=item.capability_id,
                    success=False,
                    error=error_msg,
                )
            )

    return BatchCapabilityResponse(created=created, errors=errors)
