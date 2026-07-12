"""Auto-Fix API - durable job dispatch and polling endpoints."""

from typing import Any, cast

import grpc
from fastapi import APIRouter, HTTPException, Response, status
from hatchet_sdk.clients.rest.exceptions import NotFoundException

from .dependencies import validate_project_exists
from .quality_gate_models import AutoFixJobStatus, AutoFixRequest, AutoFixResponse

router = APIRouter()


async def _get_auto_fix_run(job_id: str) -> Any:
    """Fetch one durable Hatchet run without blocking the API event loop."""
    from ..hatchet_app import hatchet

    # The deployed Hatchet server exposes its authoritative run details over
    # the SDK's admin gRPC client. The newer REST details route returns 404 for
    # valid standalone-task runs on this server version.
    return await hatchet.runs.aio_get_details(job_id)


def _job_status(value: object) -> AutoFixJobStatus | None:
    raw = getattr(value, "value", value)
    statuses: dict[str, AutoFixJobStatus] = {
        "pending": "queued",
        "queued": "queued",
        "backoff": "queued",
        "running": "running",
        "succeeded": "completed",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
    }
    return statuses.get(str(raw).lower())


def _completed_job_result(output: object) -> dict[str, Any] | None:
    """Extract a standalone task result from Hatchet's workflow output."""
    if not isinstance(output, dict):
        return None
    output_dict = cast(dict[str, Any], output)
    if {"triggered", "fixed", "failed", "escalated", "message"} <= output_dict.keys():
        return output_dict
    nested = output_dict.get("summitflow-quality-auto-fix")
    if isinstance(nested, dict):
        return cast(dict[str, Any], nested)
    return None


def _pending_response(
    *,
    job_id: str,
    job_status: AutoFixJobStatus,
    check_type: str | None,
    message: str,
) -> AutoFixResponse:
    return AutoFixResponse(
        triggered=True,
        check_type=check_type,
        fixed=0,
        failed=0,
        escalated=0,
        message=message,
        job_id=job_id,
        status=job_status,
    )


@router.post(
    "/projects/{project_id}/quality/auto-fix",
    response_model=AutoFixResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_auto_fix(
    project_id: str,
    request: AutoFixRequest,
    response: Response,
) -> AutoFixResponse:
    """Queue auto-fix work and immediately return a durable polling ID."""
    validate_project_exists(project_id)

    from ..workflows.models import AutoFixInput
    from ..workflows.utility import quality_auto_fix_wf

    workflow_run = await quality_auto_fix_wf.aio_run_no_wait(
        AutoFixInput(
            project_id=project_id,
            check_type=request.check_type,
            limit=request.limit,
        )
    )
    job_id = workflow_run.workflow_run_id
    response.headers["Location"] = f"/api/projects/{project_id}/quality/auto-fix/{job_id}"
    return _pending_response(
        job_id=job_id,
        job_status="queued",
        check_type=request.check_type,
        message=f"Auto-fix queued as job {job_id}",
    )


@router.get(
    "/projects/{project_id}/quality/auto-fix/{job_id}",
    response_model=AutoFixResponse,
)
async def get_auto_fix_job(project_id: str, job_id: str) -> AutoFixResponse:
    """Poll a durable auto-fix job, returning the original result shape."""
    validate_project_exists(project_id)

    try:
        details = await _get_auto_fix_run(job_id)
    except NotFoundException as exc:
        raise HTTPException(status_code=404, detail=f"Auto-fix job {job_id} not found") from exc
    except grpc.RpcError as exc:
        if isinstance(exc, grpc.Call) and exc.code() == grpc.StatusCode.NOT_FOUND:
            raise HTTPException(
                status_code=404,
                detail=f"Auto-fix job {job_id} not found",
            ) from exc
        raise HTTPException(
            status_code=502,
            detail="Unable to retrieve auto-fix job status",
        ) from exc

    run_input = details.input if isinstance(details.input, dict) else {}
    if str(run_input.get("project_id", "")) != project_id:
        raise HTTPException(status_code=404, detail=f"Auto-fix job {job_id} not found")

    check_type = run_input.get("check_type")
    check_type = str(check_type) if check_type is not None else None
    job_status = _job_status(details.status)
    if job_status is None:
        raise HTTPException(
            status_code=502,
            detail=f"Unknown auto-fix job status: {details.status}",
        )
    if job_status in {"queued", "running"}:
        return _pending_response(
            job_id=job_id,
            job_status=job_status,
            check_type=check_type,
            message=f"Auto-fix job {job_status}",
        )

    if job_status == "completed":
        task_outputs = {
            readable_id: task.output
            for readable_id, task in details.task_runs.items()
            if task.output is not None
        }
        result = _completed_job_result(task_outputs)
        if result is None:
            raise HTTPException(status_code=502, detail="Auto-fix job returned an invalid result")
        return AutoFixResponse.model_validate(
            {
                **result,
                "job_id": job_id,
                "status": "completed",
            }
        )

    error_message = next(
        (
            task.error
            for task in details.task_runs.values()
            if task.error
        ),
        None,
    )
    return _pending_response(
        job_id=job_id,
        job_status=job_status,
        check_type=check_type,
        message=error_message or f"Auto-fix job {job_status}",
    )
