"""Batch write handler implementations for step operations.

This module contains handlers for batch creating and appending steps.
"""

from __future__ import annotations

from fastapi import HTTPException

from ...schemas.steps import (
    BatchStepCreate,
    BatchStepResponse,
    StepResponse,
)
from .steps_handlers import handle_foreign_key_error
from .subtasks_helpers import convert_steps_to_storage_format


def create_batch_handler(
    table_id: str,
    request: BatchStepCreate,
    subtask_id: str,
    task_id: str,
) -> BatchStepResponse:
    """Create multiple steps in batch."""
    from ...storage.steps import bulk_create_steps

    steps = convert_steps_to_storage_format(request.steps)
    try:
        created = bulk_create_steps(table_id, steps)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:
        handle_foreign_key_error(e, subtask_id, task_id)
        raise  # unreachable — handle_foreign_key_error always raises
    return BatchStepResponse(
        created=[StepResponse(**s) for s in created],
        count=len(created),
    )


def append_steps_handler(
    table_id: str,
    request: BatchStepCreate,
    subtask_id: str,
    task_id: str,
) -> BatchStepResponse:
    """Append steps to a subtask."""
    from ...storage.steps import append_steps

    steps = convert_steps_to_storage_format(request.steps)
    try:
        created = append_steps(table_id, steps)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except Exception as e:
        handle_foreign_key_error(e, subtask_id, task_id)
        raise  # unreachable — handle_foreign_key_error always raises
    return BatchStepResponse(
        created=[StepResponse(**s) for s in created],
        count=len(created),
    )
