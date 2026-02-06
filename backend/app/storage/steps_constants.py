"""Constants for steps module."""

# Valid step status values
STEP_STATUS_PENDING = "pending"
STEP_STATUS_PASSED = "passed"
STEP_STATUS_FAILED = "failed"
STEP_STATUS_PLAN_DEFECT = "plan_defect"
VALID_STEP_STATUSES = {
    STEP_STATUS_PENDING,
    STEP_STATUS_PASSED,
    STEP_STATUS_FAILED,
    STEP_STATUS_PLAN_DEFECT,
}
