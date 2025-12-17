"""SummitFlow services.

Phase 3.3 services extracted from portfolio-ai:
- evidence_manager: Evidence/artifact storage and management
- verification_engine: Auto-verification engine for acceptance criteria
- feature_scanner: Feature capability scanner and validation
"""

from .evidence_manager import (
    capture_evidence,
    cleanup_old_versions,
    generate_evidence_id,
    get_evidence,
    get_evidence_base_dir,
    get_evidence_versions,
    get_expired_evidence,
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
from .feature_scanner import FeatureScanner
from .verification_engine import VerificationEngine

__all__ = [
    # Evidence manager
    "capture_evidence",
    "cleanup_old_versions",
    "generate_evidence_id",
    "get_evidence",
    "get_evidence_base_dir",
    "get_evidence_versions",
    "get_expired_evidence",
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
    # Verification engine
    "VerificationEngine",
    # Feature scanner
    "FeatureScanner",
]
