"""Request fresh owner observations; clients cannot submit successful receipts."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from ...services.native_deployment import (
    NativeDeploymentError,
    _descriptors,
    issue_native_evidence,
    read_native_evidence,
)
from ...storage.projects import get_project_root_path
from .helpers import verify_task_project

router = APIRouter()


class ObservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    acceptance_receipt: str


@router.post("/projects/{project_id}/tasks/{task_id}/deployment-observations")
async def observe_deployment(project_id: str, task_id: str, request: ObservationRequest) -> dict:
    task = await asyncio.to_thread(verify_task_project, task_id, project_id)
    project_root = await asyncio.to_thread(get_project_root_path, project_id)
    if not project_root:
        raise HTTPException(422, "Registered project checkout is unavailable")
    try:
        return await asyncio.to_thread(issue_native_evidence, task, Path(project_root), Path(request.acceptance_receipt))
    except (NativeDeploymentError, ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/projects/{project_id}/deployment-observations/{receipt_id}")
async def native_receipt(project_id: str, receipt_id: str) -> dict:
    try:
        record = await asyncio.to_thread(read_native_evidence, receipt_id, project=project_id)
        return _descriptors(record)
    except (NativeDeploymentError, ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from None
