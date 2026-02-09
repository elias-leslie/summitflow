"""Steps storage layer - CRUD operations for subtask steps.

This module provides data access for the task_subtask_steps table, which stores
normalized step data for granular completion tracking within subtasks.

Each step can have a verify_command for the tight agent feedback loop:
  code → run verify_command → fix if fail → repeat
"""

from __future__ import annotations

import logging

# Re-export from submodules for backward compatibility
from .steps_constants import (
    STEP_STATUS_FAILED,
    STEP_STATUS_PASSED,
    STEP_STATUS_PENDING,
    STEP_STATUS_PLAN_DEFECT,
    VALID_STEP_STATUSES,
)
from .steps_crud import (
    EXPECTED_STEP_COLUMNS,
    STEP_COLUMNS,
    _row_to_dict,
    append_steps,
    bulk_create_steps,
    create_step,
    delete_steps_for_subtask,
    get_step,
    get_steps_for_subtask,
    insert_step,
)
from .steps_deletion import delete_step
from .steps_exceptions import (
    PlanDefectError,
    StepDeletionResult,
    StepGateError,
    StepVerificationError,
)
from .steps_summary import get_step_summary
from .steps_updates import (
    update_step_fields,
    update_step_passes,
    update_step_status,
)
from .steps_verification import (
    VERIFY_COMMAND_TIMEOUT,
    _parse_expected,
    run_verify_command,
)

logger = logging.getLogger(__name__)

# Expose all public symbols
__all__ = [
    "EXPECTED_STEP_COLUMNS",
    "STEP_COLUMNS",
    "STEP_STATUS_FAILED",
    "STEP_STATUS_PASSED",
    "STEP_STATUS_PENDING",
    "STEP_STATUS_PLAN_DEFECT",
    "VALID_STEP_STATUSES",
    "VERIFY_COMMAND_TIMEOUT",
    "PlanDefectError",
    "StepDeletionResult",
    "StepGateError",
    "StepVerificationError",
    "_parse_expected",
    "_row_to_dict",
    "append_steps",
    "bulk_create_steps",
    "create_step",
    "delete_step",
    "delete_steps_for_subtask",
    "get_step",
    "get_step_summary",
    "get_steps_for_subtask",
    "insert_step",
    "run_verify_command",
    "update_step_fields",
    "update_step_passes",
    "update_step_status",
]
