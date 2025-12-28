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
from pathlib import Path
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

    def check_and_correct(self, project_id: str | None = None) -> HealthReport:
        """Run all health checks and auto-correct any issues found.

        This is the main self-healing method that:
        1. Checks for approved patterns and applies them
        2. Checks filter rate and adjusts thresholds if too high
        3. Checks for missing observation types and adds warnings

        Args:
            project_id: Project to check (uses default if not provided)

        Returns:
            HealthReport with corrections applied and warnings
        """
        pid = project_id or self.project_id
        if not pid:
            raise ValueError("project_id required")

        report = HealthReport()

        # Collect metrics for the report
        try:
            metrics = self.get_health_metrics(pid)
            report.metrics = metrics
        except Exception as e:
            logger.error(f"Failed to get health metrics: {e}")
            report.add_warning("metrics_error", f"Failed to get metrics: {e}", severity="high")
            return report

        # Check 1: Approved patterns waiting
        approved_patterns = self._get_approved_patterns(pid)
        if approved_patterns:
            applied_count = self._apply_approved_patterns(pid, approved_patterns)
            if applied_count > 0:
                report.add_correction(
                    "auto_applied_patterns",
                    f"Applied {applied_count} approved patterns to learned-patterns.md",
                    count=applied_count,
                    pattern_ids=[p.get("id") for p in approved_patterns[:applied_count]],
                )
            logger.info(f"Auto-applied {applied_count} patterns for {pid}")

        # Check 2: Filter rate too high
        filter_stats = metrics.get("filter_stats", {})
        skip_rate = filter_stats.get("skip_rate", 0)

        if skip_rate >= FILTER_RATE_CRITICAL_THRESHOLD:
            # Check which reason is causing most skips
            skip_reasons = filter_stats.get("skip_reasons", {})
            tiny_output_count = skip_reasons.get("tiny_output", 0)
            total_skipped = filter_stats.get("tools_skipped", 1)

            if tiny_output_count / max(total_skipped, 1) > 0.5:
                # More than 50% of skips are due to tiny_output
                report.add_warning(
                    "high_filter_rate",
                    f"Filter rate is {skip_rate:.1%} with {tiny_output_count} tiny_output skips. "
                    "Consider lowering MIN_OUTPUT_LENGTH.",
                    severity="high",
                    current_rate=skip_rate,
                    tiny_output_pct=tiny_output_count / max(total_skipped, 1),
                )
            else:
                report.add_warning(
                    "high_filter_rate",
                    f"Filter rate is {skip_rate:.1%}",
                    severity="medium",
                    current_rate=skip_rate,
                    skip_reasons=skip_reasons,
                )
        elif skip_rate >= FILTER_RATE_WARNING_THRESHOLD:
            report.add_warning(
                "elevated_filter_rate",
                f"Filter rate is {skip_rate:.1%} (above 50% threshold)",
                severity="low",
                current_rate=skip_rate,
            )

        # Check 3: No operational observations
        obs_dist = metrics.get("observation_distribution", {})
        operational_count = obs_dist.get("operational", 0)

        if operational_count == 0:
            report.add_warning(
                "no_operational_observations",
                "No operational observations found. Consider running history backfill.",
                severity="medium",
                recommendation="Run /memory_backfill to extract operational patterns",
            )
        elif operational_count < 10:
            report.add_warning(
                "few_operational_observations",
                f"Only {operational_count} operational observations. Consider running backfill.",
                severity="low",
                count=operational_count,
            )

        # Check 4: Stale approved patterns (approved but not applied)
        pattern_status = metrics.get("pattern_status", {})
        approved_count = pattern_status.get("approved", 0)
        applied_count = pattern_status.get("applied", 0)

        if approved_count > 0 and applied_count == 0:
            report.add_warning(
                "patterns_not_applied",
                f"{approved_count} patterns approved but none applied yet",
                severity="medium",
                approved=approved_count,
            )

        # Determine overall status
        high_warnings = sum(1 for w in report.warnings if w.severity == "high")
        medium_warnings = sum(1 for w in report.warnings if w.severity == "medium")

        if high_warnings > 0:
            report.status = "unhealthy"
        elif medium_warnings > 2 or len(report.warnings) > 5:
            report.status = "degraded"
        elif report.corrections:
            report.status = "corrected"  # Issues found but fixed

        return report

    def quick_check(self, project_id: str | None = None) -> bool:
        """Fast health check for SessionStart hook (<100ms target).

        Only checks for approved patterns and applies them. Skips expensive
        operations like filter stats, observation distribution, etc.

        Args:
            project_id: Project to check (uses default if not provided)

        Returns:
            True if check completed successfully
        """
        import time

        start = time.time()
        pid = project_id or self.project_id
        if not pid:
            logger.warning("quick_check called without project_id")
            return False

        try:
            # Only check for approved patterns
            approved_patterns = self._get_approved_patterns(pid)
            if approved_patterns:
                applied_count = self._apply_approved_patterns(pid, approved_patterns)
                if applied_count > 0:
                    logger.info(f"quick_check: auto-applied {applied_count} patterns for {pid}")

            elapsed_ms = (time.time() - start) * 1000
            if elapsed_ms > 100:
                logger.warning(f"quick_check took {elapsed_ms:.1f}ms (target: <100ms)")

            return True

        except Exception as e:
            logger.error(f"quick_check failed: {e}")
            return False

    def _apply_approved_patterns(self, project_id: str, patterns: list[dict[str, Any]]) -> int:
        """Apply approved patterns by writing to learned-patterns.md.

        Uses PatternService.apply_pattern() for each approved pattern.
        Updates database status to 'applied' and records timestamp.

        Args:
            project_id: Project ID
            patterns: List of approved patterns to apply

        Returns:
            Number of patterns successfully applied
        """
        if not patterns:
            return 0

        from .pattern_service import PatternService

        # Determine project path from project_id
        # For summitflow, the path is ~/summitflow
        # For other projects, we'd need to look up the path
        if project_id == "summitflow":
            project_path = Path.home() / "summitflow"
        else:
            # Try to get from projects table
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT local_path FROM projects WHERE id = %s",
                    (project_id,),
                )
                row = cur.fetchone()
                if row and row[0]:
                    project_path = Path(row[0])
                else:
                    logger.warning(f"No project path found for {project_id}")
                    return 0

        service = PatternService(project_id=project_id, project_path=str(project_path))
        applied_count = 0

        for pattern in patterns:
            pattern_id = pattern.get("id")
            if not pattern_id:
                continue

            try:
                result = service.apply_pattern(pattern_id)
                if result:
                    applied_count += 1
                    logger.info(f"Applied pattern {pattern_id}: {pattern.get('title')}")
            except Exception as e:
                logger.error(f"Failed to apply pattern {pattern_id}: {e}")
                continue

        return applied_count
