"""Memory health checker types and dataclasses.

Shared types used across the health checker modules.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Thresholds for health checks
FILTER_RATE_WARNING_THRESHOLD = 0.5  # 50% skip rate triggers warning
FILTER_RATE_CRITICAL_THRESHOLD = 0.6  # 60% skip rate triggers auto-correction
MIN_CONFIDENCE_FOR_AUTO_APPLY = 0.7  # Only auto-apply patterns with >= 70% confidence


@dataclass
class Correction:
    """A correction that was applied."""

    correction_type: str
    description: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class Warning:
    """A warning about a potential issue."""

    warning_type: str
    message: str
    severity: str = "medium"  # low, medium, high
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthReport:
    """Health check results with corrections and warnings."""

    status: str = "healthy"  # healthy, degraded, unhealthy
    corrections: list[Correction] = field(default_factory=list)
    warnings: list[Warning] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    stale_rules: list[dict[str, Any]] = field(default_factory=list)
    auto_archived: list[dict[str, Any]] = field(default_factory=list)
    sync_suggestions: list[dict[str, Any]] = field(default_factory=list)
    doc_conflicts: list[dict[str, Any]] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def add_correction(self, correction_type: str, description: str, **details: Any) -> None:
        """Add a correction to the report."""
        self.corrections.append(
            Correction(correction_type=correction_type, description=description, details=details)
        )

    def add_warning(
        self, warning_type: str, message: str, severity: str = "medium", **details: Any
    ) -> None:
        """Add a warning to the report."""
        self.warnings.append(
            Warning(warning_type=warning_type, message=message, severity=severity, details=details)
        )
        # Update status based on severity
        if severity == "high" and self.status == "healthy":
            self.status = "degraded"

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary for JSON serialization."""
        return {
            "status": self.status,
            "corrections": [
                {
                    "type": c.correction_type,
                    "description": c.description,
                    "details": c.details,
                    "timestamp": c.timestamp,
                }
                for c in self.corrections
            ],
            "warnings": [
                {
                    "type": w.warning_type,
                    "message": w.message,
                    "severity": w.severity,
                    "details": w.details,
                }
                for w in self.warnings
            ],
            "metrics": self.metrics,
            "stale_rules": self.stale_rules,
            "auto_archived": self.auto_archived,
            "sync_suggestions": self.sync_suggestions,
            "doc_conflicts": self.doc_conflicts,
            "timestamp": self.timestamp,
        }


@dataclass
class BrokenRef:
    """A broken reference found in documentation."""

    doc_file: str
    line_number: int
    reference: str
    ref_type: str  # 'file_path', 'function', 'class'
    reason: str  # Why it's broken


@dataclass
class StaleSection:
    """A stale section identified by LLM review."""

    doc_file: str
    section_title: str
    line_start: int
    staleness_reason: str
    confidence: float


@dataclass
class DeepReviewReport:
    """Comprehensive deep review of all instruction surfaces.

    Includes analysis of CLAUDE.md, AGENTS.md, rules files, and global rules.
    Identifies broken references, stale content, and token waste.
    """

    claude_md_sections: list[dict[str, Any]] = field(default_factory=list)
    agents_md_sections: list[dict[str, Any]] = field(default_factory=list)
    rules_files: list[dict[str, Any]] = field(default_factory=list)
    global_rules_files: list[dict[str, Any]] = field(default_factory=list)
    broken_refs: list[BrokenRef] = field(default_factory=list)
    stale_sections: list[StaleSection] = field(default_factory=list)
    token_waste: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary for JSON serialization."""
        return {
            "claude_md_sections": self.claude_md_sections,
            "agents_md_sections": self.agents_md_sections,
            "rules_files": self.rules_files,
            "global_rules_files": self.global_rules_files,
            "broken_refs": [
                {
                    "doc_file": r.doc_file,
                    "line_number": r.line_number,
                    "reference": r.reference,
                    "ref_type": r.ref_type,
                    "reason": r.reason,
                }
                for r in self.broken_refs
            ],
            "stale_sections": [
                {
                    "doc_file": s.doc_file,
                    "section_title": s.section_title,
                    "line_start": s.line_start,
                    "staleness_reason": s.staleness_reason,
                    "confidence": s.confidence,
                }
                for s in self.stale_sections
            ],
            "token_waste": self.token_waste,
            "timestamp": self.timestamp,
        }


def get_project_root(project_id: str) -> Path | None:
    """Get project root path from database.

    Args:
        project_id: Project ID to look up

    Returns:
        Path to project root, or None if not found
    """
    from ...storage.connection import get_connection

    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT root_path FROM projects WHERE id = %s",
                (project_id,),
            )
            row = cur.fetchone()
            if row and row[0]:
                return Path(row[0])
    except Exception as e:
        logger.warning(f"Failed to get project root for {project_id}: {e}")
    return None
