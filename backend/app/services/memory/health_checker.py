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
            "rule_adherence": self._calculate_rule_adherence(pid),
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

        # Check 1b: Auto-promote high-confidence patterns used in 2+ projects
        promoted_count = self._auto_promote_patterns()
        if promoted_count > 0:
            report.add_correction(
                "auto_promoted_patterns",
                f"Promoted {promoted_count} patterns to global scope",
                count=promoted_count,
            )

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

        # Check 5: Rule staleness and auto-archive
        stale_rules = self._check_rule_staleness(pid)
        report.stale_rules = stale_rules

        if stale_rules:
            # Auto-archive highly stale rules
            archived = self._auto_archive_stale_rules(pid, stale_rules)
            report.auto_archived = archived

            if archived:
                report.add_correction(
                    "auto_archived_rules",
                    f"Auto-archived {len(archived)} stale rules",
                    count=len(archived),
                    rules=[r["rule_file"] for r in archived],
                )

            # Warn about remaining stale rules not auto-archived
            remaining_stale = [r for r in stale_rules if r not in archived]
            if remaining_stale:
                report.add_warning(
                    "stale_rules",
                    f"{len(remaining_stale)} stale rules detected. Consider reviewing.",
                    severity="low",
                    count=len(remaining_stale),
                    rules=[r["rule_file"] for r in remaining_stale[:5]],  # Top 5
                )

        # Check 6: Doc conflicts
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

        # Check 7: Generate sync suggestions
        sync_suggestions = self._generate_sync_suggestions(pid)
        report.sync_suggestions = sync_suggestions

        if sync_suggestions:
            report.add_warning(
                "sync_suggestions",
                f"{len(sync_suggestions)} sync suggestions available",
                severity="low",
                count=len(sync_suggestions),
            )

        # Check 8: Track doc versions
        doc_versions = self._track_doc_versions(pid)
        new_versions = [d for d in doc_versions if d.get("is_new_version")]
        if new_versions:
            report.add_correction(
                "doc_versions_tracked",
                f"Tracked {len(new_versions)} doc version changes",
                count=len(new_versions),
                docs=[d["doc_file"] for d in new_versions],
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

    def _get_global_approved_patterns(self) -> list[dict[str, Any]]:
        """Get approved patterns from global scope.

        Returns:
            List of approved global patterns with confidence >= MIN_CONFIDENCE_FOR_AUTO_APPLY
        """
        patterns = memory_storage.list_patterns(
            project_id="_global_",
            status="approved",
            limit=100,
        )
        return [p for p in patterns if p.get("confidence", 0) >= MIN_CONFIDENCE_FOR_AUTO_APPLY]

    def _apply_approved_patterns(self, project_id: str, patterns: list[dict[str, Any]]) -> int:
        """Apply approved patterns by writing to learned-patterns.md.

        Uses PatternService.apply_pattern() for each approved pattern.
        Updates database status to 'applied' and records timestamp.

        For global patterns (project_id='_global_'), writes to ~/.claude/rules/learned-patterns.md
        For project patterns, writes to project/.claude/rules/learned-patterns.md

        Args:
            project_id: Project ID (or '_global_' for global patterns)
            patterns: List of approved patterns to apply

        Returns:
            Number of patterns successfully applied
        """
        if not patterns:
            return 0

        from .pattern_service import PatternService

        # Determine project path from project_id
        if project_id == "_global_":
            # Global patterns go to ~/.claude/rules/
            project_path = Path.home()
        elif project_id == "summitflow":
            project_path = Path.home() / "summitflow"
        else:
            # Try to get from projects table
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT root_path FROM projects WHERE id = %s",
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

    def _apply_global_patterns(self) -> int:
        """Apply approved global patterns to ~/.claude/rules/learned-patterns.md.

        Returns:
            Number of global patterns applied
        """
        global_patterns = self._get_global_approved_patterns()
        if not global_patterns:
            return 0

        applied = self._apply_approved_patterns("_global_", global_patterns)
        if applied > 0:
            logger.info(f"Applied {applied} global patterns to ~/.claude/rules/learned-patterns.md")
        return applied

    def _check_auto_promotion_candidates(self) -> list[dict[str, Any]]:
        """Find patterns eligible for auto-promotion to global scope.

        Criteria for auto-promotion:
        - Confidence >= 0.95
        - Applied (status='applied')
        - Same pattern title exists and is applied in 2+ different projects

        Returns:
            List of patterns eligible for auto-promotion
        """
        # Get all applied patterns with high confidence
        from ...storage.connection import get_connection

        candidates = []
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.id, p.project_id, p.title, p.content, p.confidence
                FROM learned_patterns p
                WHERE p.status = 'applied'
                  AND p.confidence >= 0.95
                  AND p.project_id != '_global_'
                  AND NOT EXISTS (
                    -- Skip if already promoted to global
                    SELECT 1 FROM learned_patterns g
                    WHERE g.project_id = '_global_'
                      AND g.title = p.title
                  )
                """
            )
            rows = cur.fetchall()

            # Group by title to find those applied in 2+ projects
            title_projects: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                pattern = {
                    "id": row[0],
                    "project_id": row[1],
                    "title": row[2],
                    "content": row[3],
                    "confidence": row[4],
                }
                title = pattern["title"]
                if title not in title_projects:
                    title_projects[title] = []
                title_projects[title].append(pattern)

            # Find patterns with same title in 2+ projects
            for _title, patterns in title_projects.items():
                unique_projects = set(p["project_id"] for p in patterns)
                if len(unique_projects) >= 2:
                    # Pick the highest confidence version
                    best = max(patterns, key=lambda p: p["confidence"])
                    candidates.append(
                        {
                            **best,
                            "project_count": len(unique_projects),
                        }
                    )

        return candidates

    def _auto_promote_patterns(self) -> int:
        """Auto-promote eligible patterns to global scope.

        Returns:
            Number of patterns promoted
        """
        from .pattern_service import PatternService

        candidates = self._check_auto_promotion_candidates()
        if not candidates:
            return 0

        promoted = 0
        for pattern in candidates:
            try:
                # Use the source project's service to promote
                service = PatternService(project_id=pattern["project_id"])
                global_pattern = service.promote_to_global(pattern["id"])

                logger.info(
                    f"auto_promoted_pattern: "
                    f"id={pattern['id']} title='{pattern['title']}' "
                    f"projects={pattern['project_count']} "
                    f"global_id={global_pattern.get('id')}"
                )
                promoted += 1

            except ValueError as e:
                logger.warning(f"Auto-promotion failed for {pattern['id']}: {e}")
                continue

        return promoted

    def _calculate_rule_adherence(self, project_id: str) -> dict[str, Any]:
        """Calculate rule adherence rates from observations.

        Queries observations with type='rule_adherence' and calculates
        the percentage of times each rule was followed vs violated.

        Args:
            project_id: Project to analyze

        Returns:
            Dict with:
                - by_rule: {rule_file: {followed: N, violated: N, rate: 0.0-1.0}}
                - overall_rate: 0.0-1.0
                - total_observations: N
        """
        from ...storage.connection import get_connection

        result: dict[str, Any] = {
            "by_rule": {},
            "overall_rate": 1.0,
            "total_observations": 0,
        }

        try:
            with get_connection() as conn, conn.cursor() as cur:
                # Query rule_adherence observations with their facts
                cur.execute(
                    """
                    SELECT
                        o.facts->>'rule_file' as rule_file,
                        (o.facts->>'rule_followed')::boolean as followed,
                        COUNT(*) as count
                    FROM observations o
                    WHERE o.project_id = %s
                      AND o.observation_type = 'rule_adherence'
                      AND o.facts->>'rule_file' IS NOT NULL
                    GROUP BY o.facts->>'rule_file', (o.facts->>'rule_followed')::boolean
                    """,
                    (project_id,),
                )
                rows = cur.fetchall()

                # Aggregate by rule file
                by_rule: dict[str, dict[str, int | float]] = {}
                total_followed = 0
                total_violated = 0

                for row in rows:
                    rule_file, followed, count = row
                    if rule_file not in by_rule:
                        by_rule[rule_file] = {"followed": 0, "violated": 0, "rate": 1.0}

                    if followed:
                        by_rule[rule_file]["followed"] += count
                        total_followed += count
                    else:
                        by_rule[rule_file]["violated"] += count
                        total_violated += count

                # Calculate rates
                for _rule_file, stats in by_rule.items():
                    total = stats["followed"] + stats["violated"]
                    if total > 0:
                        stats["rate"] = round(stats["followed"] / total, 2)

                total = total_followed + total_violated
                result["by_rule"] = by_rule
                result["total_observations"] = total
                if total > 0:
                    result["overall_rate"] = round(total_followed / total, 2)

        except Exception as e:
            logger.warning(f"Failed to calculate rule adherence: {e}")

        return result

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

    def _check_rule_staleness(self, project_id: str) -> list[dict[str, Any]]:
        """Check for stale rules in the project's .claude/rules/ directory.

        A rule is considered stale if:
        - Not modified in 90+ days AND not referenced in observations
        - Has 0% adherence rate for 60+ days

        Args:
            project_id: Project to check

        Returns:
            List of stale rule dicts with:
                - rule_file: filename
                - path: full path
                - last_modified_days: days since last modification
                - last_referenced_days: days since last observation reference (or None)
                - adherence_rate: adherence rate if tracked (or None)
                - staleness_score: 0.0-1.0 (1.0 = definitely stale)
                - reason: why it's considered stale
        """
        from datetime import datetime

        stale_rules: list[dict[str, Any]] = []

        # Get project root path
        try:
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT root_path FROM projects WHERE id = %s",
                    (project_id,),
                )
                row = cur.fetchone()
                if not row or not row[0]:
                    return []
                project_root = Path(row[0])
        except Exception as e:
            logger.warning(f"Failed to get project root for staleness check: {e}")
            return []

        rules_dir = project_root / ".claude" / "rules"
        if not rules_dir.exists():
            return []

        now = datetime.now()

        # Get rule adherence data
        adherence_data = self._calculate_rule_adherence(project_id)
        by_rule = adherence_data.get("by_rule", {})

        # Scan rule files
        for rule_file in rules_dir.glob("*.md"):
            if rule_file.name == "learned-patterns.md":
                # Skip learned-patterns.md - it's auto-managed
                continue

            filename = rule_file.name
            stat = rule_file.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime)
            days_since_modified = (now - mtime).days

            # Check for references in observations
            last_referenced_days = None
            try:
                with get_connection() as conn, conn.cursor() as cur:
                    # Check if rule is mentioned in any observation's files_modified or narrative
                    cur.execute(
                        """
                        SELECT MAX(created_at)
                        FROM observations
                        WHERE project_id = %s
                          AND (
                            files_modified::text ILIKE %s
                            OR narrative ILIKE %s
                            OR title ILIKE %s
                          )
                        """,
                        (project_id, f"%{filename}%", f"%{filename}%", f"%{filename}%"),
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        last_ref_date = row[0]
                        if hasattr(last_ref_date, "replace"):
                            # It's a datetime
                            last_referenced_days = (now - last_ref_date.replace(tzinfo=None)).days
            except Exception as e:
                logger.debug(f"Failed to check references for {filename}: {e}")

            # Get adherence rate for this rule
            adherence_rate = None
            if filename in by_rule:
                adherence_rate = by_rule[filename].get("rate")

            # Calculate staleness score
            staleness_score = 0.0
            reason = ""

            # Factor 1: Days since modification (max 0.4)
            if days_since_modified > 90:
                staleness_score += min(0.4, (days_since_modified - 90) / 180 * 0.4)

            # Factor 2: Days since referenced (max 0.3)
            if last_referenced_days is not None and last_referenced_days > 60:
                staleness_score += min(0.3, (last_referenced_days - 60) / 120 * 0.3)
            elif last_referenced_days is None and days_since_modified > 60:
                # Never referenced and old = likely stale
                staleness_score += 0.2

            # Factor 3: Low adherence rate (max 0.3)
            if adherence_rate is not None and adherence_rate < 0.2:
                staleness_score += 0.3 * (1 - adherence_rate / 0.2)

            # Build reason
            reasons = []
            if days_since_modified > 90:
                reasons.append(f"not modified in {days_since_modified} days")
            if last_referenced_days is not None and last_referenced_days > 60:
                reasons.append(f"not referenced in {last_referenced_days} days")
            elif last_referenced_days is None and days_since_modified > 30:
                reasons.append("never referenced in observations")
            if adherence_rate is not None and adherence_rate < 0.2:
                reasons.append(f"low adherence rate ({adherence_rate:.0%})")

            reason = "; ".join(reasons) if reasons else "rule appears active"

            # Only include if staleness score is significant
            if staleness_score >= 0.3:
                stale_rules.append(
                    {
                        "rule_file": filename,
                        "path": str(rule_file),
                        "last_modified_days": days_since_modified,
                        "last_referenced_days": last_referenced_days,
                        "adherence_rate": adherence_rate,
                        "staleness_score": round(staleness_score, 2),
                        "reason": reason,
                    }
                )

        # Sort by staleness score descending
        stale_rules.sort(key=lambda x: x["staleness_score"], reverse=True)

        return stale_rules

    def _auto_archive_stale_rules(
        self, project_id: str, stale_rules: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Auto-archive rules that meet high-confidence staleness criteria.

        Auto-archives if:
        - 0% adherence for 60+ days (rule_adherence tracked but never followed)
        - No references in 90+ days AND not modified in 90+ days
        - staleness_score >= 0.7

        Args:
            project_id: Project to archive rules for
            stale_rules: List of stale rules from _check_rule_staleness()

        Returns:
            List of archived rule dicts with archive_path added
        """
        import shutil
        from datetime import datetime

        archived: list[dict[str, Any]] = []

        for rule in stale_rules:
            # Check auto-archive criteria
            should_archive = False
            archive_reason = ""

            # Criterion 1: Very high staleness score
            if rule["staleness_score"] >= 0.7:
                should_archive = True
                archive_reason = f"high staleness score ({rule['staleness_score']})"

            # Criterion 2: 0% adherence (tracked but never followed)
            elif rule.get("adherence_rate") == 0.0:
                should_archive = True
                archive_reason = "0% adherence rate"

            # Criterion 3: Never referenced AND old
            elif (
                rule.get("last_referenced_days") is None and rule.get("last_modified_days", 0) > 90
            ):
                should_archive = True
                archive_reason = "never referenced and not modified in 90+ days"

            if not should_archive:
                continue

            # Archive the rule
            rule_path = Path(rule["path"])
            if not rule_path.exists():
                continue

            # Create archived directory
            archived_dir = rule_path.parent / "archived"
            archived_dir.mkdir(exist_ok=True)

            # Generate archive filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_name = f"{rule_path.stem}.{timestamp}{rule_path.suffix}"
            archive_path = archived_dir / archive_name

            try:
                # Move the file
                shutil.move(str(rule_path), str(archive_path))

                logger.info(
                    f"Auto-archived stale rule: {rule['rule_file']} -> {archive_path} "
                    f"(reason: {archive_reason})"
                )

                archived.append(
                    {
                        **rule,
                        "archive_path": str(archive_path),
                        "archive_reason": archive_reason,
                        "archived_at": datetime.now().isoformat(),
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to archive rule {rule['rule_file']}: {e}")

        return archived

    def _parse_claude_md(self, project_id: str) -> list[dict[str, Any]]:
        """Parse CLAUDE.md into structured sections.

        Extracts ## headers and their content from CLAUDE.md and AGENTS.md
        to enable conflict detection and sync suggestions.

        Args:
            project_id: Project to parse

        Returns:
            List of section dicts with:
                - doc_file: 'CLAUDE.md' or 'AGENTS.md'
                - section_title: the ## header text
                - content: text content under that header
                - line_start: line number where section starts
                - line_end: line number where section ends
        """
        import re

        sections: list[dict[str, Any]] = []

        # Get project root path
        try:
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT root_path FROM projects WHERE id = %s",
                    (project_id,),
                )
                row = cur.fetchone()
                if not row or not row[0]:
                    logger.warning(f"No project path found for {project_id}")
                    return []
                project_root = Path(row[0])
        except Exception as e:
            logger.warning(f"Failed to get project root for CLAUDE.md parsing: {e}")
            return []

        # Parse both CLAUDE.md and AGENTS.md
        doc_files = ["CLAUDE.md", "AGENTS.md"]

        for doc_file in doc_files:
            doc_path = project_root / doc_file
            if not doc_path.exists():
                continue

            try:
                content = doc_path.read_text(encoding="utf-8")
                lines = content.split("\n")

                # Pattern to match ## headers (level 2)
                header_pattern = re.compile(r"^##\s+(.+)$")

                current_section: dict[str, Any] | None = None
                section_content_lines: list[str] = []

                for i, line in enumerate(lines, start=1):
                    header_match = header_pattern.match(line)

                    if header_match:
                        # Save previous section if exists
                        if current_section:
                            current_section["content"] = "\n".join(section_content_lines).strip()
                            current_section["line_end"] = i - 1
                            sections.append(current_section)

                        # Start new section
                        current_section = {
                            "doc_file": doc_file,
                            "section_title": header_match.group(1).strip(),
                            "content": "",
                            "line_start": i,
                            "line_end": i,
                        }
                        section_content_lines = []
                    elif current_section:
                        section_content_lines.append(line)

                # Don't forget the last section
                if current_section:
                    current_section["content"] = "\n".join(section_content_lines).strip()
                    current_section["line_end"] = len(lines)
                    sections.append(current_section)

            except Exception as e:
                logger.warning(f"Failed to parse {doc_file}: {e}")
                continue

        return sections

    def _detect_doc_conflicts(self, project_id: str) -> list[dict[str, Any]]:
        """Detect conflicts between CLAUDE.md/AGENTS.md sections and learned patterns.

        Compares doc sections to patterns and flags contradictions where:
        - A pattern recommends 'use X' but doc says 'use Y'
        - A pattern deprecates something still in the docs
        - Doc and pattern give conflicting instructions on same topic

        Uses semantic similarity via embedding comparison.

        Args:
            project_id: Project to analyze

        Returns:
            List of conflict dicts with:
                - conflict_type: 'contradicting_guidance' | 'stale_reference' | 'duplicate_content'
                - doc_section: {doc_file, section_title, line_start, content_excerpt}
                - pattern: {id, title, content_excerpt}
                - explanation: why this is a conflict
                - severity: 'high' | 'medium' | 'low'
        """
        conflicts: list[dict[str, Any]] = []

        # Get doc sections
        sections = self._parse_claude_md(project_id)
        if not sections:
            return []

        # Get applied patterns for this project
        patterns = memory_storage.list_patterns(
            project_id=project_id,
            status="applied",
            limit=200,
        )

        if not patterns:
            return []

        # Compare each section against patterns for potential conflicts
        for section in sections:
            section_lower = section["content"].lower()
            section_title_lower = section["section_title"].lower()

            for pattern in patterns:
                pattern_content = pattern.get("content", "").lower()
                pattern_title = pattern.get("title", "").lower()

                # Skip empty content
                if not pattern_content or not section_lower:
                    continue

                # Check for duplicate content (high similarity)
                if self._is_similar_content(section_lower, pattern_content, threshold=0.6):
                    conflicts.append(
                        {
                            "conflict_type": "duplicate_content",
                            "doc_section": {
                                "doc_file": section["doc_file"],
                                "section_title": section["section_title"],
                                "line_start": section["line_start"],
                                "content_excerpt": section["content"][:200],
                            },
                            "pattern": {
                                "id": pattern.get("id"),
                                "title": pattern.get("title"),
                                "content_excerpt": pattern.get("content", "")[:200],
                            },
                            "explanation": f"Pattern '{pattern.get('title')}' has similar content to "
                            f"section '{section['section_title']}' in {section['doc_file']}. "
                            "Consider consolidating.",
                            "severity": "low",
                        }
                    )
                    continue

                # Check for contradicting guidance
                # Look for opposing keywords
                contradictions = self._check_for_contradictions(
                    section_lower, pattern_content, section_title_lower, pattern_title
                )

                if contradictions:
                    conflicts.append(
                        {
                            "conflict_type": "contradicting_guidance",
                            "doc_section": {
                                "doc_file": section["doc_file"],
                                "section_title": section["section_title"],
                                "line_start": section["line_start"],
                                "content_excerpt": section["content"][:200],
                            },
                            "pattern": {
                                "id": pattern.get("id"),
                                "title": pattern.get("title"),
                                "content_excerpt": pattern.get("content", "")[:200],
                            },
                            "explanation": contradictions,
                            "severity": "high"
                            if "must" in section_lower or "never" in section_lower
                            else "medium",
                        }
                    )

        return conflicts

    def _is_similar_content(self, text1: str, text2: str, threshold: float = 0.6) -> bool:
        """Check if two texts are semantically similar using word overlap.

        Simple heuristic based on significant word overlap.

        Args:
            text1: First text to compare
            text2: Second text to compare
            threshold: Jaccard similarity threshold (0.0-1.0)

        Returns:
            True if similarity exceeds threshold
        """

        # Extract significant words (length > 3)
        def get_words(text: str) -> set[str]:
            words = set()
            for word in text.split():
                # Remove punctuation
                word = word.strip(".,;:!?()[]{}\"'")
                if len(word) > 3 and word.isalpha():
                    words.add(word.lower())
            return words

        words1 = get_words(text1)
        words2 = get_words(text2)

        if not words1 or not words2:
            return False

        # Jaccard similarity
        intersection = len(words1 & words2)
        union = len(words1 | words2)

        return (intersection / union) >= threshold if union > 0 else False

    def _check_for_contradictions(
        self, doc_content: str, pattern_content: str, doc_title: str, pattern_title: str
    ) -> str | None:
        """Check if doc section and pattern have contradicting guidance.

        Looks for patterns like:
        - Doc says 'use X' but pattern says 'avoid X' or 'use Y instead of X'
        - Doc says 'never X' but pattern says 'always X'
        - Doc says 'prefer X' but pattern says 'prefer Y' on same topic

        Args:
            doc_content: Lowercase doc section content
            pattern_content: Lowercase pattern content
            doc_title: Lowercase doc section title
            pattern_title: Lowercase pattern title

        Returns:
            Explanation string if contradiction found, None otherwise
        """
        # Check for same topic (title similarity)
        if not self._is_similar_content(doc_title, pattern_title, threshold=0.3):
            return None

        # Opposing keyword pairs
        opposites = [
            ("always", "never"),
            ("use", "avoid"),
            ("prefer", "avoid"),
            ("required", "optional"),
            ("must", "should not"),
            ("recommended", "deprecated"),
            ("enable", "disable"),
        ]

        for word1, word2 in opposites:
            # Check if doc has word1 and pattern has word2, or vice versa
            if (word1 in doc_content and word2 in pattern_content) or (
                word2 in doc_content and word1 in pattern_content
            ):
                return (
                    f"Potential conflict: doc uses '{word1}'/'{word2}' guidance "
                    f"that may contradict pattern guidance"
                )

        return None

    def _generate_sync_suggestions(self, project_id: str) -> list[dict[str, Any]]:
        """Generate suggestions for synchronizing patterns with CLAUDE.md.

        Suggests:
        - pattern_should_be_in_claude_md: High-confidence patterns not in docs
        - doc_section_could_be_pattern: Doc sections that could become patterns
        - pattern_duplicates_doc: Pattern content already in docs

        Args:
            project_id: Project to analyze

        Returns:
            List of suggestion dicts with:
                - suggestion_type: Type of suggestion
                - pattern_id: Pattern ID (if applicable)
                - pattern_title: Pattern title (if applicable)
                - doc_file: Doc file (if applicable)
                - section_title: Doc section title (if applicable)
                - suggestion: Human-readable suggestion text
                - action: Recommended action ('add_to_claude_md', 'create_pattern', 'consolidate')
        """
        suggestions: list[dict[str, Any]] = []

        # Get doc sections
        sections = self._parse_claude_md(project_id)

        # Get high-confidence applied patterns
        patterns = memory_storage.list_patterns(
            project_id=project_id,
            status="applied",
            limit=200,
        )

        # Suggestion 1: High-confidence patterns not covered by CLAUDE.md
        section_content_combined = " ".join(s["content"].lower() for s in sections).lower()

        for pattern in patterns:
            confidence = pattern.get("confidence", 0)
            pattern_title = pattern.get("title", "")
            pattern_content = pattern.get("content", "")

            # Skip low confidence patterns
            if confidence < 0.85:
                continue

            # Check if pattern content is already covered in docs
            if not self._is_similar_content(
                pattern_content.lower(), section_content_combined, threshold=0.4
            ):
                # High-confidence pattern not in docs
                suggestions.append(
                    {
                        "suggestion_type": "pattern_should_be_in_claude_md",
                        "pattern_id": pattern.get("id"),
                        "pattern_title": pattern_title,
                        "doc_file": None,
                        "section_title": None,
                        "suggestion": f"Pattern '{pattern_title}' (confidence: {confidence:.0%}) "
                        "has proven useful and should be added to CLAUDE.md for visibility.",
                        "action": "add_to_claude_md",
                    }
                )

        # Suggestion 2: Doc sections that look like they could be learned patterns
        # (imperative guidance not tracked as patterns)
        guidance_keywords = ["must", "always", "never", "required", "mandatory", "forbidden"]

        for section in sections:
            section_content_lower = section["content"].lower()

            # Check if section has strong guidance
            has_guidance = any(kw in section_content_lower for kw in guidance_keywords)

            if has_guidance and len(section["content"]) < 500:  # Concise enough for pattern
                # Check if there's already a matching pattern
                matching_pattern = None
                for pattern in patterns:
                    if self._is_similar_content(
                        section["content"].lower(),
                        pattern.get("content", "").lower(),
                        threshold=0.5,
                    ):
                        matching_pattern = pattern
                        break

                if not matching_pattern:
                    suggestions.append(
                        {
                            "suggestion_type": "doc_section_could_be_pattern",
                            "pattern_id": None,
                            "pattern_title": None,
                            "doc_file": section["doc_file"],
                            "section_title": section["section_title"],
                            "suggestion": f"Section '{section['section_title']}' in {section['doc_file']} "
                            "contains guidance that could be tracked as a learned pattern "
                            "for adherence monitoring.",
                            "action": "create_pattern",
                        }
                    )

        return suggestions

    def _track_doc_versions(self, project_id: str) -> list[dict[str, Any]]:
        """Track document versions by storing content hashes as observations.

        Stores CLAUDE.md and AGENTS.md content hashes to enable:
        - Detecting when docs have changed
        - Querying version history
        - Triggering sync suggestions on changes

        Args:
            project_id: Project to track

        Returns:
            List of tracked doc dicts with:
                - doc_file: filename
                - content_hash: SHA-256 hash
                - is_new_version: whether this is a new hash
        """
        import hashlib

        tracked: list[dict[str, Any]] = []

        # Get project root path
        try:
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT root_path FROM projects WHERE id = %s",
                    (project_id,),
                )
                row = cur.fetchone()
                if not row or not row[0]:
                    return []
                project_root = Path(row[0])
        except Exception as e:
            logger.warning(f"Failed to get project root for doc version tracking: {e}")
            return []

        doc_files = ["CLAUDE.md", "AGENTS.md"]

        for doc_file in doc_files:
            doc_path = project_root / doc_file
            if not doc_path.exists():
                continue

            try:
                content = doc_path.read_text(encoding="utf-8")
                content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

                # Check if we already have this version tracked
                with get_connection() as conn, conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT narrative FROM observations
                        WHERE project_id = %s
                          AND observation_type = 'doc_version'
                          AND title = %s
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        (project_id, doc_file),
                    )
                    row = cur.fetchone()
                    existing_hash = row[0] if row else None

                is_new_version = existing_hash != content_hash

                if is_new_version:
                    # Store new version observation
                    memory_storage.create_observation(
                        project_id=project_id,
                        session_id="health-check",
                        agent_type="health-checker",
                        observation_type="doc_version",
                        title=doc_file,
                        narrative=content_hash,
                        priority="low",
                        confidence=1.0,
                        facts={"content_length": len(content), "previous_hash": existing_hash},
                    )
                    logger.info(f"Tracked new doc version: {doc_file} -> {content_hash}")

                tracked.append(
                    {
                        "doc_file": doc_file,
                        "content_hash": content_hash,
                        "is_new_version": is_new_version,
                    }
                )

            except Exception as e:
                logger.warning(f"Failed to track version for {doc_file}: {e}")
                continue

        return tracked

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

        report = DeepReviewReport()

        # Get project root path
        try:
            with get_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT root_path FROM projects WHERE id = %s",
                    (pid,),
                )
                row = cur.fetchone()
                if not row or not row[0]:
                    logger.warning(f"No project path found for {pid}")
                    return report
                project_root = Path(row[0])
        except Exception as e:
            logger.warning(f"Failed to get project root for deep review: {e}")
            return report

        # Review CLAUDE.md
        claude_md_path = project_root / "CLAUDE.md"
        if claude_md_path.exists():
            report.claude_md_sections = self._parse_claude_md(pid)
            # Check for broken refs
            broken = self._check_references(claude_md_path, project_root)
            report.broken_refs.extend(broken)

        # Review AGENTS.md
        agents_md_path = project_root / "AGENTS.md"
        if agents_md_path.exists():
            agents_sections = self._parse_doc_sections(agents_md_path, "AGENTS.md")
            report.agents_md_sections = agents_sections
            broken = self._check_references(agents_md_path, project_root)
            report.broken_refs.extend(broken)

        # Review project rules (.claude/rules/)
        rules_dir = project_root / ".claude" / "rules"
        if rules_dir.exists():
            for rule_file in rules_dir.glob("*.md"):
                rule_info = {
                    "name": rule_file.name,
                    "path": str(rule_file),
                    "size_bytes": rule_file.stat().st_size,
                    "last_modified": datetime.fromtimestamp(rule_file.stat().st_mtime).isoformat(),
                }
                report.rules_files.append(rule_info)
                broken = self._check_references(rule_file, project_root)
                report.broken_refs.extend(broken)

        # Review global rules (~/.claude/rules/)
        global_rules_dir = Path.home() / ".claude" / "rules"
        if global_rules_dir.exists():
            for rule_file in global_rules_dir.glob("*.md"):
                rule_info = {
                    "name": rule_file.name,
                    "path": str(rule_file),
                    "size_bytes": rule_file.stat().st_size,
                    "last_modified": datetime.fromtimestamp(rule_file.stat().st_mtime).isoformat(),
                }
                report.global_rules_files.append(rule_info)

        # Calculate token waste
        report.token_waste = self._calculate_token_waste(report)

        return report

    def _parse_doc_sections(self, doc_path: Path, doc_file: str) -> list[dict[str, Any]]:
        """Parse a markdown document into sections.

        Args:
            doc_path: Path to the markdown file
            doc_file: Name for the doc_file field

        Returns:
            List of section dicts with doc_file, section_title, content, line_start, line_end
        """
        import re

        sections: list[dict[str, Any]] = []

        try:
            content = doc_path.read_text(encoding="utf-8")
            lines = content.split("\n")

            header_pattern = re.compile(r"^##\s+(.+)$")
            current_section: dict[str, Any] | None = None
            section_content_lines: list[str] = []

            for i, line in enumerate(lines, start=1):
                header_match = header_pattern.match(line)

                if header_match:
                    if current_section:
                        current_section["content"] = "\n".join(section_content_lines).strip()
                        current_section["line_end"] = i - 1
                        sections.append(current_section)

                    current_section = {
                        "doc_file": doc_file,
                        "section_title": header_match.group(1).strip(),
                        "content": "",
                        "line_start": i,
                        "line_end": i,
                    }
                    section_content_lines = []
                elif current_section:
                    section_content_lines.append(line)

            if current_section:
                current_section["content"] = "\n".join(section_content_lines).strip()
                current_section["line_end"] = len(lines)
                sections.append(current_section)

        except Exception as e:
            logger.warning(f"Failed to parse {doc_file}: {e}")

        return sections

    def _check_references(self, doc_path: Path, project_root: Path) -> list[BrokenRef]:
        """Check for broken references in a document.

        Parses markdown for file paths, function names, and class names,
        then verifies they exist in the filesystem.

        Patterns matched:
        - `backend/app/...` backtick-wrapped file paths
        - 'See X.py' or 'in X.py'
        - 'the X function' or 'function X()'
        - 'class X' references

        Args:
            doc_path: Path to the document
            project_root: Project root for resolving references

        Returns:
            List of BrokenRef objects for broken references
        """
        import re

        broken_refs: list[BrokenRef] = []
        doc_file = doc_path.name

        try:
            content = doc_path.read_text(encoding="utf-8")
            lines = content.split("\n")

            # Patterns to find references
            patterns = [
                # Backtick-wrapped file paths: `backend/app/main.py`
                (re.compile(r"`([a-zA-Z0-9_/.-]+\.(py|ts|tsx|js|jsx|md))`"), "file_path"),
                # In/See file references: See main.py, in utils.py
                (
                    re.compile(
                        r"(?:See|in|from)\s+`?([a-zA-Z0-9_.-]+\.(?:py|ts|tsx|js|jsx|md))`?",
                        re.IGNORECASE,
                    ),
                    "file_path",
                ),
                # File path with directory: backend/app/api/memory.py
                (
                    re.compile(
                        r"(?<!`)((?:backend|frontend|app|src)/[a-zA-Z0-9_/.-]+\.(?:py|ts|tsx|js|jsx))"
                    ),
                    "file_path",
                ),
            ]

            for line_num, line in enumerate(lines, start=1):
                for pattern, ref_type in patterns:
                    matches = pattern.finditer(line)
                    for match in matches:
                        ref = match.group(1)

                        # Skip if it's a URL or external path
                        if ref.startswith("http") or ref.startswith("/usr") or ref.startswith("~"):
                            continue

                        # Check if file exists
                        ref_path = project_root / ref
                        if not ref_path.exists():
                            # Also check if it might be a basename match
                            found = False
                            for suffix in ["", ".py", ".ts", ".tsx", ".js", ".jsx"]:
                                if (project_root / (ref + suffix)).exists():
                                    found = True
                                    break

                            if not found:
                                broken_refs.append(
                                    BrokenRef(
                                        doc_file=doc_file,
                                        line_number=line_num,
                                        reference=ref,
                                        ref_type=ref_type,
                                        reason=f"File not found: {ref}",
                                    )
                                )

        except Exception as e:
            logger.warning(f"Failed to check references in {doc_file}: {e}")

        return broken_refs

    def _calculate_token_waste(self, report: DeepReviewReport) -> dict[str, Any]:
        """Calculate token waste from stale/redundant content.

        Placeholder - will be implemented in task 7.4.

        Args:
            report: The deep review report with sections

        Returns:
            Dict with token waste metrics
        """
        # Will be implemented in task 7.4
        return {
            "total_tokens": 0,
            "waste_tokens": 0,
            "waste_pct": 0.0,
            "by_source": {},
        }
