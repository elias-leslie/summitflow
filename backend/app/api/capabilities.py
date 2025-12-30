"""Capabilities API - CRUD for TDD capabilities."""

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..storage import capabilities as storage
from ..storage import explorer as explorer_storage
from ..storage import tests as tests_storage

router = APIRouter()


class CapabilityCreate(BaseModel):
    """Request model for creating a capability."""

    component_id: int
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


class VerifyResult(BaseModel):
    """Response model for capability verification result."""

    capability_id: str
    capability_status: str
    tests_total: int
    tests_passed: int
    tests_failed: int
    evidence_captured: bool


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
    """Get a specific capability with linked tests."""
    capability = storage.get_capability(project_id, capability_id)
    if not capability:
        raise HTTPException(status_code=404, detail=f"Capability {capability_id} not found")

    # Get linked tests for this capability
    tests = tests_storage.get_tests_for_capability(project_id, capability["id"])

    return CapabilityWithTestsResponse(**capability, tests=tests)


@router.post("/{project_id}/capabilities", response_model=CapabilityResponse)
async def create_capability(project_id: str, body: CapabilityCreate) -> CapabilityResponse:
    """Create a new capability."""
    try:
        capability = storage.create_capability(
            project_id=project_id,
            component_id=body.component_id,
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
                detail=f"Component with id {body.component_id} not found",
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


@router.post("/{project_id}/capabilities/{capability_id}/verify", response_model=VerifyResult)
async def verify_capability(project_id: str, capability_id: str) -> VerifyResult:
    """Verify a capability by checking its linked tests.

    Returns the verification result including test counts and evidence status.
    If all tests pass and verification_url is set, captures evidence.
    """
    capability = storage.get_capability(project_id, capability_id)
    if not capability:
        raise HTTPException(status_code=404, detail=f"Capability {capability_id} not found")

    # Get linked tests for this capability
    tests = tests_storage.get_tests_for_capability(project_id, capability_id)

    # Count test results based on last_result
    tests_passed = 0
    tests_failed = 0
    for test in tests:
        result = test.get("last_result")
        if result == "passed":
            tests_passed += 1
        elif result in ("failed", "error", "timeout"):
            tests_failed += 1
        # If result is None/null, test hasn't been run yet (counts as failed)
        else:
            tests_failed += 1

    tests_total = len(tests)
    evidence_captured = False

    # Note: Evidence capture is deferred - requires criterion_id integration
    # For now, verification_url is stored but evidence capture happens via
    # the existing /evidence/capture endpoint when needed.
    # TODO: Add criterion-level or capability-level evidence capture

    # Get latest capability status (may have been updated by test runs)
    capability = storage.get_capability(project_id, capability_id)

    return VerifyResult(
        capability_id=capability_id,
        capability_status=capability["status"] if capability else "pending",
        tests_total=tests_total,
        tests_passed=tests_passed,
        tests_failed=tests_failed,
        evidence_captured=evidence_captured,
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
