"""Shared constants used across the application."""

from typing import Literal, get_args

# =============================================================================
# Task Type Constants
# =============================================================================

TaskType = Literal["feature", "bug", "task", "refactor", "debt", "regression"]
TASK_TYPE_VALUES: tuple[str, ...] = get_args(TaskType)

# =============================================================================
# Agent Hub Routing Constants
# =============================================================================
# Workloads route by agent slug. Agent Hub owns provider/model choice.

AGENT_WORKER = "agent:coder"
AGENT_SUPERVISOR = "agent:supervisor"
AGENT_REVIEWER = "agent:reviewer"
AGENT_DEBUGGER = "agent:debugger"  # Bug fixing with root cause analysis
AGENT_TRIAGER = "agent:triager"
AGENT_IMAGE_GEN = "image-gen"
AGENT_PLANNER = "planner"
AGENT_SPECIFIER = "specifier"


# =============================================================================
# QA Review Thresholds
# =============================================================================
# These control when the QA review loop escalates to different agents/modes

# Number of worker retry attempts before escalating to supervisor
QA_WORKER_STUCK_THRESHOLD = 3

# Number of supervisor attempts before full escalation
QA_SUPERVISOR_STUCK_THRESHOLD = 2

# =============================================================================
# Self-Healing Retry Constants
# =============================================================================
# When step verification fails, agent gets a chance to self-correct before escalating

# Number of pristine self-heal attempts before blocking task execution
PRISTINE_SELF_HEAL_MAX_ATTEMPTS = 3

# Number of self-fix attempts before requesting supervisor guidance
SELF_HEAL_MAX_ATTEMPTS = 3

# Number of supervisor-guided fix attempts before full escalation
SUPERVISOR_GUIDED_MAX_ATTEMPTS = 3

# Context window usage threshold (%) for starting a fresh session
CONTEXT_FRESHNESS_THRESHOLD = 80

# Total number of QA review attempts before full escalation
QA_ESCALATION_THRESHOLD = 5

# Maximum number of QA review iterations before giving up
QA_MAX_ITERATIONS = 50
