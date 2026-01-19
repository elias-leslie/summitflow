"""Self-healing services for automated error detection and resolution."""

from .attempt_history import (
    Attempt,
    AttemptHistory,
    TaskAttemptHistory,
    compute_diff_hash,
)
from .attempt_history import compute_error_hash as compute_attempt_error_hash
from .graphiti_client import FixPattern, GraphitiClient, SearchResult
from .monitor import (
    JournalError,
    SystemdMonitor,
    compute_error_hash,
    create_error_task,
    process_journal_errors,
)
from .orchestrator import SelfHealingOrchestrator, poll_and_fix_all
from .pattern_memory import PatternMemoryService, StoredPattern, compute_error_signature

__all__ = [
    "Attempt",
    "AttemptHistory",
    "FixPattern",
    "GraphitiClient",
    "JournalError",
    "PatternMemoryService",
    "SearchResult",
    "SelfHealingOrchestrator",
    "StoredPattern",
    "SystemdMonitor",
    "TaskAttemptHistory",
    "compute_attempt_error_hash",
    "compute_diff_hash",
    "compute_error_hash",
    "compute_error_signature",
    "create_error_task",
    "poll_and_fix_all",
    "process_journal_errors",
]
