"""Tasks API - Acceptance criteria management.

Handles:
- validate_task_criteria
- list_task_criteria
- create_task_criterion
- delete_task_criterion
- batch_create_task_criteria
- verify_task_criterion_junction

Note: This module uses task_acceptance_criteria table (direct task ownership)
rather than the old acceptance_criteria + task_criteria junction pattern.
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
    UpdateTaskCriterionRequest,
    VerifyTaskCriterionRequest,
)
from ...services.criteria_validator import validate_criteria
from ...storage.connection import get_connection
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


@router.get(
    "/projects/{project_id}/tasks/{task_id}/criteria",
    response_model=list[dict[str, Any]],
)
async def list_task_criteria(
    project_id: str,
    task_id: str,
) -> list[dict[str, Any]]:
    """List all criteria for a task with verification status.

    Uses task_acceptance_criteria table (direct task ownership).
    Returns criteria with verification state including verified, verified_at.

    Args:
        project_id: Project ID
        task_id: Task ID

    Returns:
        List of criterion dicts with verification state.
    """
    _verify_task_project(task_id, project_id)

    from ...storage.verification import get_criteria_for_task_v2

    with get_connection() as conn:
        criteria = get_criteria_for_task_v2(conn, task_id)

    return criteria


@router.post(
    "/projects/{project_id}/tasks/{task_id}/criteria",
    response_model=dict[str, Any],
)
async def create_task_criterion(
    project_id: str,
    task_id: str,
    request: CreateTaskCriterionRequest,
) -> dict[str, Any]:
    """Create a criterion directly in task_acceptance_criteria.

    Uses task_acceptance_criteria table for direct task ownership.
    No junction table - criterion belongs directly to task.

    Args:
        project_id: Project ID
        task_id: Task ID
        request: Criterion details

    Returns:
        Created criterion with id and criterion_id.
    """
    _verify_task_project(task_id, project_id)

    from ...storage.verification import create_task_criterion as create_task_criterion_v2

    with get_connection() as conn:
        # Create the criterion directly in task_acceptance_criteria
        criterion = create_task_criterion_v2(
            conn=conn,
            task_id=task_id,
            criterion=request.criterion,
            category=request.category,
            verify_by=request.verify_by,
            verify_command=request.verify_command,
            expected_output=request.expected_output,
        )

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
        "verify_command": criterion.get("verify_command"),
        "verify_by": criterion["verify_by"],
        "expected_output": criterion.get("expected_output"),
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
    """Delete a criterion from task_acceptance_criteria.

    Args:
        project_id: Project ID
        task_id: Task ID
        criterion_id: Criterion ID (format: ac-NNN)

    Returns:
        Status dict.
    """
    _verify_task_project(task_id, project_id)

    from ...storage.verification import get_task_criterion

    with get_connection() as conn:
        criterion = get_task_criterion(conn, task_id, criterion_id)
        if not criterion:
            raise HTTPException(
                status_code=404,
                detail=f"Criterion {criterion_id} not found for task {task_id}",
            )

        # Delete directly from task_acceptance_criteria
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM task_acceptance_criteria WHERE task_id = %s AND criterion_id = %s",
            (task_id, criterion_id),
        )
        deleted = cur.rowcount > 0
        conn.commit()

    return {
        "status": "deleted" if deleted else "not_found",
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
    """Create multiple criteria directly in task_acceptance_criteria.

    Uses task_acceptance_criteria table for direct task ownership.
    Handles partial failures: returns both created criteria and errors.

    Args:
        project_id: Project ID
        task_id: Task ID
        request: List of criteria to create

    Returns:
        BatchTaskCriteriaResponse with created criteria and any errors.
    """
    _verify_task_project(task_id, project_id)

    from ...storage.verification import create_task_criterion as create_task_criterion_v2

    created: list[dict[str, Any]] = []
    errors: list[BatchCriterionResult] = []

    with get_connection() as conn:
        for item in request.items:
            try:
                # Create the criterion directly in task_acceptance_criteria
                criterion = create_task_criterion_v2(
                    conn=conn,
                    task_id=task_id,
                    criterion=item.criterion,
                    category=item.category,
                    verify_by=item.verify_by,
                    verify_command=item.verify_command,
                    expected_output=item.expected_output,
                )

                created.append(
                    {
                        "id": criterion["id"],
                        "criterion_id": criterion["criterion_id"],
                        "criterion": criterion["criterion"],
                        "category": criterion["category"],
                        "verify_command": criterion.get("verify_command"),
                        "verify_by": criterion["verify_by"],
                        "expected_output": criterion.get("expected_output"),
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
    """Update verification status in task_acceptance_criteria.

    Args:
        project_id: Project ID
        task_id: Task ID
        criterion_id: Criterion ID (format: ac-NNN)
        request: Verification details

    Returns:
        Status dict with updated verification info.
    """
    _verify_task_project(task_id, project_id)

    from datetime import UTC, datetime

    from ...storage.verification import get_task_criterion, update_task_criterion

    with get_connection() as conn:
        criterion = get_task_criterion(conn, task_id, criterion_id)
        if not criterion:
            raise HTTPException(
                status_code=404,
                detail=f"Criterion {criterion_id} not found for task {task_id}",
            )

        now = datetime.now(UTC)
        updated = update_task_criterion(
            conn,
            task_id,
            criterion_id,
            {
                "verified": request.verified,
                "verified_at": now if request.verified else None,
                "verified_by_actual": request.verified_by,
            },
        )

        if not updated:
            raise HTTPException(
                status_code=404,
                detail=f"Criterion {criterion_id} not found for task {task_id}",
            )

    return {
        "status": "verified" if request.verified else "unverified",
        "task_id": task_id,
        "criterion_id": criterion_id,
        "verified_by": request.verified_by,
    }


@router.patch(
    "/projects/{project_id}/tasks/{task_id}/criteria/{criterion_id}",
    response_model=dict[str, Any],
)
async def update_task_criterion(
    project_id: str,
    task_id: str,
    criterion_id: str,
    request: UpdateTaskCriterionRequest,
) -> dict[str, Any]:
    """Update a criterion's fields in task_acceptance_criteria.

    Args:
        project_id: Project ID
        task_id: Task ID
        criterion_id: Criterion ID (format: ac-NNN)
        request: Fields to update

    Returns:
        Updated criterion dict.
    """
    _verify_task_project(task_id, project_id)

    from ...storage.verification import get_task_criterion, update_task_criterion

    with get_connection() as conn:
        criterion = get_task_criterion(conn, task_id, criterion_id)
        if not criterion:
            raise HTTPException(
                status_code=404,
                detail=f"Criterion {criterion_id} not found for task {task_id}",
            )

        # Build updates dict from non-None fields
        updates = {}
        if request.criterion is not None:
            updates["criterion"] = request.criterion
        if request.category is not None:
            updates["category"] = request.category
        if request.verify_command is not None:
            updates["verify_command"] = request.verify_command
        if request.verify_by is not None:
            updates["verify_by"] = request.verify_by
        if request.expected_output is not None:
            updates["expected_output"] = request.expected_output

        if not updates:
            # No updates, just return current criterion
            return criterion

        updated = update_task_criterion(conn, task_id, criterion_id, updates)

        if not updated:
            raise HTTPException(
                status_code=404,
                detail=f"Criterion {criterion_id} not found for task {task_id}",
            )

    logger.info(
        "task_criterion_updated",
        task_id=task_id,
        criterion_id=criterion_id,
        fields=list(updates.keys()),
    )

    return updated
