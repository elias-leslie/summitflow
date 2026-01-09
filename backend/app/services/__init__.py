"""SummitFlow services.

Services:
- evidence_manager: Evidence/artifact storage and management
- agent_hub: Agent Hub autocode task dispatch
"""

from .agent_hub import (
    AgentHubService,
    EvidenceContract,
    ExecutionState,
    TaskContext,
    dispatch_task,
    validate_evidence,
)
from .evidence_manager import (
    capture_evidence,
    cleanup_old_versions,
    generate_evidence_id,
    get_auto_captured_evidence,
    get_evidence,
    get_evidence_base_dir,
    get_evidence_versions,
    get_latest_evidence,
    get_needs_user_review,
    get_next_version,
    get_pending_review,
    get_summary,
    get_with_user_notes,
    read_evidence_file,
    save_evidence,
    update_ai_review,
    update_user_review,
)

__all__ = [
    "AgentHubService",
    "EvidenceContract",
    "ExecutionState",
    "TaskContext",
    "capture_evidence",
    "cleanup_old_versions",
    "dispatch_task",
    "generate_evidence_id",
    "get_auto_captured_evidence",
    "get_evidence",
    "get_evidence_base_dir",
    "get_evidence_versions",
    "get_latest_evidence",
    "get_needs_user_review",
    "get_next_version",
    "get_pending_review",
    "get_summary",
    "get_with_user_notes",
    "read_evidence_file",
    "save_evidence",
    "update_ai_review",
    "update_user_review",
    "validate_evidence",
]
