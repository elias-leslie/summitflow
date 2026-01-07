"""Tasks API - Acceptance criteria management.

Handles:
- validate_task_criteria
- create_task_criterion
- delete_task_criterion
- batch_create_task_criteria
- verify_task_criterion_junction
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ...logging_config import get_logger
from ...schemas.tasks import (
    BatchCriterionResult,
    BatchTaskCriteriaRequest,
    BatchTaskCriteriaResponse,
    CreateTaskCriterionRequest,
    CriteriaValidateRequest,
    CriteriaValidateResponse,
    CriterionFailure,
    VerifyTaskCriterionRequest,
)
from ...services.criteria_validator import validate_criteria
from ...storage.connection import get_connection
from ...storage.criteria import (
    create_criterion,
    get_criterion,
    link_criterion_to_task,
    unlink_criterion_from_task,
    update_task_criterion_verification,
)
from .core import _verify_task_project

logger = get_logger(__name__)

router = APIRouter()


@router.post(
    "/projects/{project_id}/tasks/criteria/validate",
    response_model=CriteriaValidateResponse,
)
async def validate_task_criteria(
    project_id: str, request: CriteriaValidateRequest
) -> CriteriaValidateResponse:
    """Validate acceptance criteria quality using Opus.

    Evaluates each criterion against quality checklist:
    - Specific: Concrete, unambiguous behavior
    - Measurable: Can be verified with yes/no answer
    - Testable: Can be verified by automated test
    - Threshold: Performance criteria have concrete values

    Args:
        project_id: Project ID (for future project-specific validation rules)
        request: Objective and criteria to validate

    Returns:
        Validation result with overall validity and per-criterion failures.
    """
    result = validate_criteria(request.objective, request.criteria)

    return CriteriaValidateResponse(
        valid=result.valid,
        failures=[
            CriterionFailure(
                criterion_id=f.criterion_id,
                valid=f.valid,
                issues=f.issues,
                suggestion=f.suggestion,
            )
            for f in result.failures
        ],
    )


@router.post(
    "/projects/{project_id}/tasks/{task_id}/criteria",
    response_model=dict[str, Any],
)
async def create_task_criterion(
    project_id: str,
    task_id: str,
    request: CreateTaskCriterionRequest,
) -> dict[str, Any]:
    """Create a criterion and link it to a task.

    Creates a new entry in acceptance_criteria and links it via task_criteria.
    These are "standalone" criteria that exist only for this task.

    Args:
        project_id: Project ID
        task_id: Task ID
        request: Criterion details

    Returns:
        Created criterion with id and criterion_id.
    """
    _verify_task_project(task_id, project_id)

    with get_connection() as conn:
        # Create the criterion
        criterion = create_criterion(
            conn=conn,
            project_id=project_id,
            criterion=request.criterion,
            category=request.category,
            measurement=request.measurement,
            threshold=request.threshold,
            created_by_task_id=task_id,
        )

        # Link to task
        link_criterion_to_task(conn, task_id, criterion["id"])

        logger.info(
            "task_criterion_created",
            task_id=task_id,
            criterion_id=criterion["criterion_id"],
        )

    return {
        "id": criterion["id"],
        "criterion_id": criterion["criterion_id"],
        "criterion": criterion["criterion"],
        "category": criterion["category"],
        "measurement": criterion["measurement"],
        "threshold": criterion["threshold"],
        "task_id": task_id,
    }


@router.delete(
    "/projects/{project_id}/tasks/{task_id}/criteria/{criterion_id}",
    response_model=dict[str, Any],
)
async def delete_task_criterion(
    project_id: str,
    task_id: str,
    criterion_id: str,
) -> dict[str, Any]:
    """Unlink a criterion from a task.

    Removes the link from task_criteria. If criterion becomes orphaned
    (no links in capability_criteria or task_criteria), it's deleted.

    Args:
        project_id: Project ID
        task_id: Task ID
        criterion_id: Criterion ID (format: ac-NNN)

    Returns:
        Status dict.
    """
    _verify_task_project(task_id, project_id)

    with get_connection() as conn:
        criterion = get_criterion(conn, project_id, criterion_id)
        if not criterion:
            raise HTTPException(
                status_code=404,
                detail=f"Criterion {criterion_id} not found",
            )

        removed = unlink_criterion_from_task(conn, task_id, criterion["id"])

    return {
        "status": "removed" if removed else "not_found",
        "task_id": task_id,
        "criterion_id": criterion_id,
    }


@router.post(
    "/projects/{project_id}/tasks/{task_id}/criteria/batch",
    response_model=BatchTaskCriteriaResponse,
    status_code=201,
)
async def batch_create_task_criteria(
    project_id: str,
    task_id: str,
    request: BatchTaskCriteriaRequest,
) -> BatchTaskCriteriaResponse:
    """Create multiple criteria and link them to a task in batch.

    Handles partial failures: returns both created criteria and errors.
    Each criterion is created independently, so failures don't rollback successes.

    Args:
        project_id: Project ID
        task_id: Task ID
        request: List of criteria to create

    Returns:
        BatchTaskCriteriaResponse with created criteria and any errors.
    """
    _verify_task_project(task_id, project_id)

    created: list[dict[str, Any]] = []
    errors: list[BatchCriterionResult] = []

    with get_connection() as conn:
        for item in request.items:
            try:
                # Create the criterion
                criterion = create_criterion(
                    conn=conn,
                    project_id=project_id,
                    criterion=item.criterion,
                    category=item.category,
                    measurement=item.measurement,
                    threshold=item.threshold,
                    created_by_task_id=task_id,
                )

                # Link to task
                link_criterion_to_task(conn, task_id, criterion["id"])

                created.append(
                    {
                        "id": criterion["id"],
                        "criterion_id": criterion["criterion_id"],
                        "criterion": criterion["criterion"],
                        "category": criterion["category"],
                        "measurement": criterion["measurement"],
                        "threshold": criterion["threshold"],
                        "task_id": task_id,
                    }
                )

                logger.info(
                    "batch_task_criterion_created",
                    task_id=task_id,
                    criterion_id=criterion["criterion_id"],
                )
            except Exception as e:
                errors.append(
                    BatchCriterionResult(
                        criterion=item.criterion[:50],
                        success=False,
                        error=str(e),
                    )
                )

    return BatchTaskCriteriaResponse(created=created, errors=errors)


@router.patch(
    "/projects/{project_id}/tasks/{task_id}/criteria/{criterion_id}/verify",
    response_model=dict[str, Any],
)
async def verify_task_criterion_junction(
    project_id: str,
    task_id: str,
    criterion_id: str,
    request: VerifyTaskCriterionRequest,
) -> dict[str, Any]:
    """Update verification status for a task's criterion.

    Updates the verified/verified_at/verified_by fields in task_criteria.

    Args:
        project_id: Project ID
        task_id: Task ID
        criterion_id: Criterion ID (format: ac-NNN)
        request: Verification details

    Returns:
        Status dict with updated verification info.
    """
    _verify_task_project(task_id, project_id)

    with get_connection() as conn:
        criterion = get_criterion(conn, project_id, criterion_id)
        if not criterion:
            raise HTTPException(
                status_code=404,
                detail=f"Criterion {criterion_id} not found",
            )

        updated = update_task_criterion_verification(
            conn=conn,
            task_id=task_id,
            criterion_db_id=criterion["id"],
            verified=request.verified,
            verified_by=request.verified_by,
        )

        if not updated:
            raise HTTPException(
                status_code=404,
                detail=f"Criterion {criterion_id} not linked to task {task_id}",
            )

    return {
        "status": "verified" if request.verified else "unverified",
        "task_id": task_id,
        "criterion_id": criterion_id,
        "verified_by": request.verified_by,
    }
