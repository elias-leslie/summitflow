"""Components API - CRUD for TDD components."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..storage import components as storage

router = APIRouter()


class ComponentCreate(BaseModel):
    """Request model for creating a component."""

    component_id: str
    name: str
    description: str | None = None
    priority: int = 2
    explorer_entry_id: int | None = None


class ComponentUpdate(BaseModel):
    """Request model for updating a component."""

    name: str | None = None
    description: str | None = None
    priority: int | None = None
    status: str | None = None
    explorer_entry_id: int | None = None


class ComponentResponse(BaseModel):
    """Response model for a component."""

    id: int
    project_id: str
    component_id: str
    name: str
    description: str | None = None
    priority: int
    status: str
    created_at: str | None = None
    updated_at: str | None = None
    explorer_entry_id: int | None = None


@router.get("/{project_id}/components", response_model=list[ComponentResponse])
async def list_components(project_id: str) -> list[ComponentResponse]:
    """List all components for a project."""
    components_list = storage.list_components(project_id)
    return [ComponentResponse(**c) for c in components_list]


@router.get("/{project_id}/components/{component_id}", response_model=ComponentResponse)
async def get_component(project_id: str, component_id: str) -> ComponentResponse:
    """Get a specific component."""
    component = storage.get_component(project_id, component_id)
    if not component:
        raise HTTPException(status_code=404, detail=f"Component {component_id} not found")
    return ComponentResponse(**component)


@router.post("/{project_id}/components", response_model=ComponentResponse)
async def create_component(project_id: str, body: ComponentCreate) -> ComponentResponse:
    """Create a new component."""
    try:
        component = storage.create_component(
            project_id=project_id,
            component_id=body.component_id,
            name=body.name,
            description=body.description,
            priority=body.priority,
            explorer_entry_id=body.explorer_entry_id,
        )
        return ComponentResponse(**component)
    except Exception as e:
        if "duplicate key" in str(e).lower() or "unique constraint" in str(e).lower():
            raise HTTPException(
                status_code=409,
                detail=f"Component {body.component_id} already exists",
            ) from e
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.patch("/{project_id}/components/{component_id}", response_model=ComponentResponse)
async def update_component(
    project_id: str, component_id: str, body: ComponentUpdate
) -> ComponentResponse:
    """Update a component."""
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    component = storage.update_component(project_id, component_id, **updates)
    if not component:
        raise HTTPException(status_code=404, detail=f"Component {component_id} not found")

    return ComponentResponse(**component)


@router.delete("/{project_id}/components/{component_id}")
async def delete_component(project_id: str, component_id: str) -> dict[str, str]:
    """Delete a component."""
    deleted = storage.delete_component(project_id, component_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Component {component_id} not found")

    return {"status": "deleted", "component_id": component_id}


# =============================================================================
# Batch Endpoints
# =============================================================================


class BatchComponentCreate(BaseModel):
    """Request model for batch component creation."""

    items: list[ComponentCreate]


class BatchCreateResult(BaseModel):
    """Result for a single item in batch create."""

    component_id: str
    success: bool
    id: int | None = None
    error: str | None = None


class BatchComponentResponse(BaseModel):
    """Response model for batch component creation."""

    created: list[ComponentResponse]
    errors: list[BatchCreateResult]


@router.post("/{project_id}/components/batch", response_model=BatchComponentResponse)
async def batch_create_components(
    project_id: str, body: BatchComponentCreate
) -> BatchComponentResponse:
    """Create multiple components in a single request.

    Handles partial failures: returns both created components and errors.
    Each component is created independently, so failures don't rollback successes.

    Args:
        project_id: Project ID
        body: List of components to create

    Returns:
        BatchComponentResponse with created components and any errors.
    """
    created: list[ComponentResponse] = []
    errors: list[BatchCreateResult] = []

    for item in body.items:
        try:
            component = storage.create_component(
                project_id=project_id,
                component_id=item.component_id,
                name=item.name,
                description=item.description,
                priority=item.priority,
                explorer_entry_id=item.explorer_entry_id,
            )
            created.append(ComponentResponse(**component))
        except Exception as e:
            error_msg = str(e)
            if "duplicate key" in error_msg.lower() or "unique constraint" in error_msg.lower():
                error_msg = f"Component {item.component_id} already exists"
            errors.append(
                BatchCreateResult(
                    component_id=item.component_id,
                    success=False,
                    error=error_msg,
                )
            )

    return BatchComponentResponse(created=created, errors=errors)
