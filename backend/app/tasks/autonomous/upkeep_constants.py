"""Shared constants for routine upkeep task generation."""

ROUTINE_UPKEEP_WORKFLOW = "routine_upkeep"
LOCK_PREFIX = "summitflow:routine-upkeep:"
FEEDBACK_TIMEOUT_SECONDS = 30.0
UPKEEP_LABELS = ["routine-upkeep", "auto-generated"]
REQUEST_SOURCE = "sf-routine-upkeep"
SOURCE_CLIENT = "summitflow"
TOOL_NAME = "routine-upkeep"
SOURCE_QUALITY = "quality"
SOURCE_FEEDBACK = "feedback"
SOURCE_REFACTORS = "refactors"
SOURCE_CONSOLIDATE = "consolidate-duplicate"
# Rollout gate for consolidate-duplicate filing. The redundancy detector is
# precision-proven on well-layered backend/frontend apps but domain-ambiguous on
# codebases with heavy per-entity polymorphism (e.g. monkey-fight's game engine,
# where getFramePose/drawDetails/darken legitimately recur per character/scene).
# Until the cross-project review signs off on global rollout, only file
# consolidation tasks for allowlisted projects. Override with the
# CONSOLIDATION_PROJECT_ALLOWLIST env var: a comma-separated project list, or "*"
# to enable everywhere.
CONSOLIDATION_ALLOWLIST_ENV = "CONSOLIDATION_PROJECT_ALLOWLIST"
DEFAULT_CONSOLIDATION_ALLOWLIST = frozenset({"summitflow", "agent-hub", "portfolio-ai"})
SOURCES = (SOURCE_REFACTORS, SOURCE_QUALITY, SOURCE_FEEDBACK)
STATUS_ACTIVE = "active"
STATUS_COMPLETED = "completed"
STATUS_DISABLED = "disabled"
STATUS_SKIPPED = "skipped"
STATUS_BLOCKED = "blocked"
STATUS_FAILED = "failed"
SORT_VOTES = "votes"
TASK_TYPE_BUG = "bug"
TASK_TYPE_TASK = "task"
COMPLEXITY_SIMPLE = "SIMPLE"
EXECUTION_MODE_AUTONOMOUS = "autonomous"
SUBTASK_ID = "1.1"
SUBTASK_TYPE_BUG_FIX = "bug-fix"
PHASE_BACKEND = "backend"
PHASE_IMPLEMENTATION = "implementation"
REASON_NOT_DUE = "not_due"
REASON_ALREADY_RUNNING = "already_running"
DISPATCH_FAILURE_STATUSES = {"disabled", "unhealthy", "daily_limit", "concurrency_limit"}
QUALITY_DEFAULTS = {
    "check_type": SOURCE_QUALITY,
    "check_name": "unknown",
    "file_path": "project",
    "line_number": "any",
}
EMPTY_KEY_PARTS = {"-", "unknown", "None", "null"}
DONE_WHEN = [
    "The underlying upkeep signal is resolved or explicitly marked obsolete with evidence",
    "Relevant targeted checks pass through st check",
    "No unrelated behavior changes are introduced",
]
