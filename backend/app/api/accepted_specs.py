"""Accepted Specs API - Query accepted spec definitions."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..storage import accepted_specs as storage

router = APIRouter()


class SpecResponse(BaseModel):
    """Response model for an accepted spec."""

    id: int
    project_id: str
    spec_json: dict
    accepted_at: str | None = None
    accepted_by: str | None = None
    notes: str | None = None
    created_at: str | None = None


@router.get("/{project_id}/specs", response_model=list[SpecResponse])
async def list_specs(project_id: str) -> list[SpecResponse]:
    """List all accepted specs for a project."""
    specs_list = storage.list_accepted_specs(project_id)
    return [SpecResponse(**s) for s in specs_list]


@router.get("/{project_id}/specs/latest", response_model=SpecResponse)
async def get_latest_spec(project_id: str) -> SpecResponse:
    """Get the most recently accepted spec for a project."""
    spec = storage.get_latest_accepted_spec(project_id)
    if not spec:
        raise HTTPException(status_code=404, detail="No accepted specs found")
    return SpecResponse(**spec)


@router.get("/{project_id}/specs/{spec_id}", response_model=SpecResponse)
async def get_spec(project_id: str, spec_id: int) -> SpecResponse:
    """Get a specific accepted spec by ID."""
    spec = storage.get_accepted_spec(spec_id)
    if not spec or spec.get("project_id") != project_id:
        raise HTTPException(status_code=404, detail=f"Spec {spec_id} not found")
    return SpecResponse(**spec)
