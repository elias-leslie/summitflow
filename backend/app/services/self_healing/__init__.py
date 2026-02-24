"""Self-healing services for automated error detection and resolution."""

from .memory_client import FixPattern, GraphitiClient, MemoryClient, SearchResult
from .monitor import (
    JournalError,
    SystemdMonitor,
    compute_error_hash,
    create_error_task,
    process_journal_errors,
)
from .orchestrator import (
    BUDGET_CAP_USD,
    BudgetExceededError,
    SelfHealingOrchestrator,
    poll_and_fix_all,
)
from .pattern_memory import PatternMemoryService, StoredPattern, compute_error_signature

__all__ = [
    "BUDGET_CAP_USD",
    "BudgetExceededError",
    "FixPattern",
    "GraphitiClient",  # Deprecated alias, use MemoryClient
    "MemoryClient",
    "JournalError",
    "PatternMemoryService",
    "SearchResult",
    "SelfHealingOrchestrator",
    "StoredPattern",
    "SystemdMonitor",
    "compute_error_hash",
    "compute_error_signature",
    "create_error_task",
    "poll_and_fix_all",
    "process_journal_errors",
]
