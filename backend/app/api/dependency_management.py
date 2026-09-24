"""Shared dependency inventory and revisioned review API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.dependency_management import list_inventory, record_decision, review_dependency
from .dependencies import validate_project_exists

router = APIRouter()


class ReviewRequest(BaseModel):
    entry_path: str = Field(min_length=1)
    refresh: bool = False


class DecisionRequest(BaseModel):
    entry_path: str = Field(min_length=1)
    decision: str
    rationale: str = Field(min_length=1)
    expected_revision: int = Field(ge=1)
    recommended_version: str | None = None
    queue_task: bool = False


@router.get("/{project_id}/dependencies")
def dependencies_list(
    project_id: str,
    ecosystem: str | None = None,
    status: str | None = None,
    query: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    validate_project_exists(project_id)
    return list_inventory(project_id, ecosystem=ecosystem, status=status, query=query, limit=limit, offset=offset)


@router.post("/{project_id}/dependencies/review")
def dependencies_review(project_id: str, body: ReviewRequest) -> dict[str, Any]:
    validate_project_exists(project_id)
    try:
        return review_dependency(project_id, body.entry_path, refresh=body.refresh)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{project_id}/dependencies/record")
def dependencies_record(project_id: str, body: DecisionRequest) -> dict[str, Any]:
    validate_project_exists(project_id)
    try:
        return {"record": record_decision(
            project_id, body.entry_path, decision=body.decision,
            rationale=body.rationale, expected_revision=body.expected_revision,
            recommended_version=body.recommended_version, queue_task=body.queue_task,
        )}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
