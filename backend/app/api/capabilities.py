"""Capabilities API - CRUD for TDD capabilities."""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..storage import capabilities as storage
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
    created_at: str | None = None
    updated_at: str | None = None


class CapabilityWithTestsResponse(CapabilityResponse):
    """Response model for capability with linked tests."""

    tests: list[dict] = []


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
            )
        if "violates foreign key constraint" in str(e).lower():
            raise HTTPException(
                status_code=400,
                detail=f"Component with id {body.component_id} not found",
            )
        raise HTTPException(status_code=500, detail=str(e))


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


@router.post(
    "/{project_id}/capabilities/{capability_id}/unlock", response_model=CapabilityResponse
)
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
