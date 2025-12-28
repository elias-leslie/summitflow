"""Memory health checker with self-healing capabilities.

Detects issues in the memory system and auto-corrects them:
- Approved patterns waiting → auto-apply
- Filter rate too high → adjust thresholds
- Missing observation types → add warnings
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ...storage import memory as memory_storage
from ...storage.connection import get_connection

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
            "timestamp": self.timestamp,
        }


class MemoryHealthChecker:
    """Self-healing health checker for context memory system.

    Usage:
        checker = MemoryHealthChecker()
        report = checker.check_and_correct("summitflow")
        print(report.status, len(report.corrections))
    """

    def __init__(self, project_id: str | None = None):
        """Initialize health checker.

        Args:
            project_id: Default project ID for operations
        """
        self.project_id = project_id

    def _get_approved_patterns(self, project_id: str) -> list[dict[str, Any]]:
        """Get patterns in 'approved' status waiting to be applied.

        Returns:
            List of approved patterns with id, title, confidence, content
        """
        patterns = memory_storage.list_patterns(
            project_id=project_id,
            status="approved",
            limit=100,
        )
        return [p for p in patterns if p.get("confidence", 0) >= MIN_CONFIDENCE_FOR_AUTO_APPLY]

    def _get_filter_stats(self, project_id: str | None = None) -> dict[str, Any]:
        """Get tool filtering statistics from hooks.

        Returns:
            Dict with tools_received, tools_queued, tools_skipped, skip_reasons
        """
        from ...api.hooks import get_filtering_metrics

        metrics = get_filtering_metrics()
        return {
            "tools_received": metrics.get("tools_received", 0),
            "tools_queued": metrics.get("tools_queued", 0),
            "tools_skipped": metrics.get("tools_skipped", 0),
            "skip_reasons": metrics.get("skip_reasons", {}),
            "skip_rate": (
                metrics.get("tools_skipped", 0) / max(metrics.get("tools_received", 1), 1)
            ),
        }

    def _get_observation_distribution(self, project_id: str) -> dict[str, int]:
        """Get observation count by type.

        Returns:
            Dict mapping observation_type to count
        """
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT observation_type, COUNT(*) as count
                FROM observations
                WHERE project_id = %s
                GROUP BY observation_type
                ORDER BY count DESC
                """,
                (project_id,),
            )
            rows = cur.fetchall()
            return {row[0]: row[1] for row in rows}

    def _get_pattern_status_breakdown(self, project_id: str) -> dict[str, int]:
        """Get pattern count by status.

        Returns:
            Dict mapping status to count
        """
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT status, COUNT(*) as count
                FROM learned_patterns
                WHERE project_id = %s
                GROUP BY status
                """,
                (project_id,),
            )
            rows = cur.fetchall()
            return {row[0]: row[1] for row in rows}

    def _get_embedding_coverage(self, project_id: str) -> dict[str, Any]:
        """Get embedding coverage statistics.

        Returns:
            Dict with total, with_embeddings, coverage_pct
        """
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE embedding IS NOT NULL) as with_embeddings
                FROM observations
                WHERE project_id = %s
                """,
                (project_id,),
            )
            row = cur.fetchone()
            total = row[0] if row else 0
            with_emb = row[1] if row else 0
            return {
                "total": total,
                "with_embeddings": with_emb,
                "coverage_pct": (with_emb / max(total, 1)) * 100,
            }

    def get_health_metrics(self, project_id: str | None = None) -> dict[str, Any]:
        """Get comprehensive health metrics.

        Args:
            project_id: Project to check (uses default if not provided)

        Returns:
            Dict with all health metrics
        """
        pid = project_id or self.project_id
        if not pid:
            raise ValueError("project_id required")

        return {
            "filter_stats": self._get_filter_stats(pid),
            "observation_distribution": self._get_observation_distribution(pid),
            "pattern_status": self._get_pattern_status_breakdown(pid),
            "embedding_coverage": self._get_embedding_coverage(pid),
            "approved_patterns_waiting": len(self._get_approved_patterns(pid)),
        }
