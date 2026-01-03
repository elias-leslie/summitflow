"""Memory health checker with self-healing capabilities.

Detects issues in the memory system and auto-corrects them:
- Approved patterns waiting → auto-apply
- Filter rate too high → adjust thresholds
- Missing observation types → add warnings

This is the main orchestrator - actual logic is in submodules:
- types.py: Dataclasses and constants
- pattern_applier.py: Pattern application logic
- rule_staleness.py: Rule staleness checking
- doc_analyzer.py: Document analysis and sync
- deep_review.py: Deep review functionality
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ...storage.memory_health import (
    get_embedding_coverage,
    get_observation_distribution,
    get_pattern_status_breakdown,
)
from ...storage.memory_patterns import (
    cleanup_low_relevance_patterns,
    enforce_pattern_cap,
)
from ...utils.rate_limiter import get_cleanup_settings

# Import from submodules
from .deep_review import deep_review as _deep_review
from .doc_analyzer import (
    detect_doc_conflicts,
    generate_sync_suggestions,
    parse_claude_md,
    track_doc_versions,
)
from .pattern_applier import (
    apply_approved_patterns,
    auto_promote_patterns,
    get_approved_patterns,
)
from .rule_staleness import (
    auto_archive_stale_rules,
    calculate_rule_adherence,
    check_rule_staleness,
)
from .types import (
    FILTER_RATE_CRITICAL_THRESHOLD,
    FILTER_RATE_WARNING_THRESHOLD,
    MIN_CONFIDENCE_FOR_AUTO_APPLY,
    BrokenRef,
    Correction,
    DeepReviewReport,
    HealthReport,
    StaleSection,
    Warning,
)

logger = logging.getLogger(__name__)

# Re-export for backwards compatibility
__all__ = [
    "FILTER_RATE_CRITICAL_THRESHOLD",
    "FILTER_RATE_WARNING_THRESHOLD",
    "MIN_CONFIDENCE_FOR_AUTO_APPLY",
    "BrokenRef",
    "Correction",
    "DeepReviewReport",
    "HealthReport",
    "MemoryHealthChecker",
    "StaleSection",
    "Warning",
]


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
        """Get patterns in 'approved' status waiting to be applied."""
        return get_approved_patterns(project_id)

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
        """Get observation count by type."""
        return get_observation_distribution(project_id)

    def _get_pattern_status_breakdown(self, project_id: str) -> dict[str, int]:
        """Get pattern count by status."""
        return get_pattern_status_breakdown(project_id)

    def _get_embedding_coverage(self, project_id: str) -> dict[str, Any]:
        """Get embedding coverage statistics."""
        return get_embedding_coverage(project_id)

    def _calculate_rule_adherence(self, project_id: str) -> dict[str, Any]:
        """Calculate rule adherence rates from observations."""
        return calculate_rule_adherence(project_id)

    def _apply_approved_patterns(self, project_id: str, patterns: list[dict[str, Any]]) -> int:
        """Mark approved patterns as 'applied' in the database."""
        return apply_approved_patterns(project_id, patterns)

    def _auto_promote_patterns(self) -> int:
        """Auto-promote eligible patterns to global scope."""
        return auto_promote_patterns()

    def _check_rule_staleness(self, project_id: str) -> list[dict[str, Any]]:
        """Check for stale rules in the project's .claude/rules/ directory."""
        return check_rule_staleness(project_id)

    def _auto_archive_stale_rules(
        self, project_id: str, stale_rules: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Auto-archive rules that meet high-confidence staleness criteria."""
        return auto_archive_stale_rules(project_id, stale_rules)

    def _parse_claude_md(self, project_id: str) -> list[dict[str, Any]]:
        """Parse CLAUDE.md into structured sections."""
        return parse_claude_md(project_id)

    def _detect_doc_conflicts(self, project_id: str) -> list[dict[str, Any]]:
        """Detect conflicts between CLAUDE.md/AGENTS.md sections and learned patterns."""
        return detect_doc_conflicts(project_id)

    def _generate_sync_suggestions(self, project_id: str) -> list[dict[str, Any]]:
        """Generate suggestions for synchronizing patterns with CLAUDE.md."""
        return generate_sync_suggestions(project_id)

    def _track_doc_versions(self, project_id: str) -> list[dict[str, Any]]:
        """Track document versions by storing content hashes as observations."""
        return track_doc_versions(project_id)

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
            "rule_adherence": self._calculate_rule_adherence(pid),
        }

    def _check_approved_patterns(self, pid: str, report: HealthReport) -> None:
        """Check and apply approved patterns."""
        approved_patterns = self._get_approved_patterns(pid)
        if approved_patterns:
            applied_count = self._apply_approved_patterns(pid, approved_patterns)
            if applied_count > 0:
                report.add_correction(
                    "auto_applied_patterns",
                    f"Marked {applied_count} approved patterns as applied",
                    count=applied_count,
                    pattern_ids=[p.get("id") for p in approved_patterns[:applied_count]],
                )
            logger.info(f"Auto-applied {applied_count} patterns for {pid}")

        # Auto-promote high-confidence patterns used in 2+ projects
        promoted_count = self._auto_promote_patterns()
        if promoted_count > 0:
            report.add_correction(
                "auto_promoted_patterns",
                f"Promoted {promoted_count} patterns to global scope",
                count=promoted_count,
            )

    def _check_filter_rate(self, metrics: dict[str, Any], report: HealthReport) -> None:
        """Check filter rate and add warnings if too high."""
        filter_stats = metrics.get("filter_stats", {})
        skip_rate = filter_stats.get("skip_rate", 0)

        if skip_rate >= FILTER_RATE_CRITICAL_THRESHOLD:
            skip_reasons = filter_stats.get("skip_reasons", {})
            tiny_output_count = skip_reasons.get("tiny_output", 0)
            total_skipped = filter_stats.get("tools_skipped", 1)

            if tiny_output_count / max(total_skipped, 1) > 0.5:
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

    def _check_operational_observations(
        self, metrics: dict[str, Any], report: HealthReport
    ) -> None:
        """Check for missing operational observations."""
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

        # Check stale approved patterns
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

    def _run_pattern_lifecycle(self, pid: str, report: HealthReport) -> None:
        """Run pattern lifecycle cleanup operations.

        - Cleanup low-relevance patterns (based on global cleanup settings)
        - Enforce pattern cap (50 per project)
        """
        # Get cleanup settings from Redis (controlled by /memory page slider)
        cleanup_settings = get_cleanup_settings()
        min_relevance = cleanup_settings["min_relevance"]
        min_age_days = cleanup_settings["min_age_days"]

        # Skip cleanup if in manual mode (level 0)
        if cleanup_settings["level"] == 0:
            logger.debug("Pattern cleanup skipped: manual mode enabled")
            return

        # Cleanup low-relevance patterns
        cleaned = cleanup_low_relevance_patterns(
            min_relevance=min_relevance, min_age_days=min_age_days
        )
        if cleaned:
            report.add_correction(
                "cleaned_low_relevance_patterns",
                f"Deleted {len(cleaned)} low-relevance patterns",
                count=len(cleaned),
                patterns=[p["title"] for p in cleaned[:5]],
            )
            logger.info(f"Cleaned up {len(cleaned)} low-relevance patterns")

        # Enforce pattern cap per project
        capped = enforce_pattern_cap(pid, max_patterns=50)
        if capped:
            report.add_correction(
                "enforced_pattern_cap",
                f"Removed {len(capped)} patterns to enforce cap of 50",
                count=len(capped),
                patterns=[p["title"] for p in capped[:5]],
            )
            logger.info(f"Enforced pattern cap for {pid}: removed {len(capped)} patterns")

    def _check_rules_and_docs(self, pid: str, report: HealthReport) -> None:
        """Check rule staleness and doc conflicts."""
        # Rule staleness and auto-archive
        stale_rules = self._check_rule_staleness(pid)
        report.stale_rules = stale_rules

        if stale_rules:
            archived = self._auto_archive_stale_rules(pid, stale_rules)
            report.auto_archived = archived

            if archived:
                report.add_correction(
                    "auto_archived_rules",
                    f"Auto-archived {len(archived)} stale rules",
                    count=len(archived),
                    rules=[r["rule_file"] for r in archived],
                )

            remaining_stale = [r for r in stale_rules if r not in archived]
            if remaining_stale:
                report.add_warning(
                    "stale_rules",
                    f"{len(remaining_stale)} stale rules detected. Consider reviewing.",
                    severity="low",
                    count=len(remaining_stale),
                    rules=[r["rule_file"] for r in remaining_stale[:5]],
                )

        # Doc conflicts
        conflicts = self._detect_doc_conflicts(pid)
        report.doc_conflicts = conflicts

        if conflicts:
            high_severity = [c for c in conflicts if c.get("severity") == "high"]
            if high_severity:
                report.add_warning(
                    "doc_conflicts",
                    f"{len(high_severity)} high-severity conflicts between docs and patterns",
                    severity="high",
                    count=len(high_severity),
                )

        # Sync suggestions
        sync_suggestions = self._generate_sync_suggestions(pid)
        report.sync_suggestions = sync_suggestions

        if sync_suggestions:
            report.add_warning(
                "sync_suggestions",
                f"{len(sync_suggestions)} sync suggestions available",
                severity="low",
                count=len(sync_suggestions),
            )

        # Track doc versions
        doc_versions = self._track_doc_versions(pid)
        new_versions = [d for d in doc_versions if d.get("is_new_version")]
        if new_versions:
            report.add_correction(
                "doc_versions_tracked",
                f"Tracked {len(new_versions)} doc version changes",
                count=len(new_versions),
                docs=[d["doc_file"] for d in new_versions],
            )

    def check_and_correct(self, project_id: str | None = None) -> HealthReport:
        """Run all health checks and auto-correct any issues found.

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

        # Run checks (each modifies report in place)
        self._check_approved_patterns(pid, report)
        self._check_filter_rate(metrics, report)
        self._check_operational_observations(metrics, report)
        self._check_rules_and_docs(pid, report)
        self._run_pattern_lifecycle(pid, report)

        # Determine overall status
        high_warnings = sum(1 for w in report.warnings if w.severity == "high")
        medium_warnings = sum(1 for w in report.warnings if w.severity == "medium")

        if high_warnings > 0:
            report.status = "unhealthy"
        elif medium_warnings > 2 or len(report.warnings) > 5:
            report.status = "degraded"
        elif report.corrections:
            report.status = "corrected"

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

    def get_threshold_recommendations(self, project_id: str | None = None) -> list[dict[str, Any]]:
        """Get recommendations for adjusting thresholds.

        Analyzes filter statistics and recommends threshold changes
        to improve observation capture rate.

        Args:
            project_id: Project to analyze (uses default if not provided)

        Returns:
            List of recommendation dicts with type, current, recommended, reason
        """
        pid = project_id or self.project_id
        if not pid:
            return []

        recommendations: list[dict[str, Any]] = []

        try:
            filter_stats = self._get_filter_stats(pid)
        except Exception as e:
            logger.warning(f"Failed to get filter stats for recommendations: {e}")
            return []

        skip_reasons = filter_stats.get("skip_reasons", {})
        total_skipped = filter_stats.get("tools_skipped", 0)
        total_received = filter_stats.get("tools_received", 1)

        if total_skipped == 0:
            return []

        # Check tiny_output ratio
        tiny_output_count = skip_reasons.get("tiny_output", 0)
        tiny_output_ratio = tiny_output_count / max(total_skipped, 1)

        if tiny_output_ratio > 0.5:
            # More than 50% of skips are due to tiny_output
            # Recommend lowering MIN_OUTPUT_LENGTH

            # Current threshold is 200 chars (from hooks.py)
            current_threshold = 200

            # Calculate what threshold would capture 80% of currently skipped
            # This is a heuristic - we'd need output length distribution for accuracy
            # For now, recommend halving if high skip rate
            skip_rate = filter_stats.get("skip_rate", 0)

            if skip_rate > 0.5:
                recommended = current_threshold // 2  # 100
                confidence = "high"
            elif skip_rate > 0.3:
                recommended = int(current_threshold * 0.75)  # 150
                confidence = "medium"
            else:
                recommended = current_threshold
                confidence = "low"

            if recommended != current_threshold:
                recommendations.append(
                    {
                        "type": "min_output_length",
                        "current": current_threshold,
                        "recommended": recommended,
                        "confidence": confidence,
                        "reason": f"Tiny output causes {tiny_output_ratio:.0%} of skips. "
                        f"Lowering threshold could capture {tiny_output_count} more observations.",
                        "impact": {
                            "additional_observations": tiny_output_count,
                            "pct_of_skipped": tiny_output_ratio * 100,
                        },
                    }
                )

        # Check bash pattern skips
        bash_skip_count = skip_reasons.get("skip_bash_pattern", 0)
        bash_skip_ratio = bash_skip_count / max(total_received, 1)

        if bash_skip_ratio > 0.1:
            # More than 10% of all tools are bash pattern skips
            recommendations.append(
                {
                    "type": "bash_skip_patterns",
                    "current": "default patterns",
                    "recommended": "review patterns",
                    "confidence": "medium",
                    "reason": f"Bash pattern filter is skipping {bash_skip_ratio:.1%} of all tools. "
                    "Consider reviewing SKIP_BASH_PATTERNS in hooks.py.",
                    "impact": {
                        "skipped_count": bash_skip_count,
                        "pct_of_total": bash_skip_ratio * 100,
                    },
                }
            )

        return recommendations

    def deep_review(self, project_id: str | None = None) -> DeepReviewReport:
        """Perform comprehensive deep review of all instruction surfaces.

        Analyzes:
        - CLAUDE.md sections
        - AGENTS.md sections
        - Project .claude/rules/ files
        - Global ~/.claude/rules/ files
        - Broken references to files/functions/classes
        - Token waste calculation

        Args:
            project_id: Project to review (uses default if not provided)

        Returns:
            DeepReviewReport with findings
        """
        pid = project_id or self.project_id
        if not pid:
            raise ValueError("Project ID required for deep review")

        return _deep_review(pid)
