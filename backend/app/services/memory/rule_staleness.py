"""Rule staleness checking for the memory health checker.

Handles detection and auto-archiving of stale rules.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from ...storage.connection import get_connection
from .types import get_project_root

logger = logging.getLogger(__name__)


def calculate_rule_adherence(project_id: str) -> dict[str, Any]:
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


def check_rule_staleness(project_id: str) -> list[dict[str, Any]]:
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
    stale_rules: list[dict[str, Any]] = []

    # Get project root path
    project_root = get_project_root(project_id)
    if not project_root:
        return []

    rules_dir = project_root / ".claude" / "rules"
    if not rules_dir.exists():
        return []

    now = datetime.now()

    # Get rule adherence data
    adherence_data = calculate_rule_adherence(project_id)
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


def auto_archive_stale_rules(
    project_id: str, stale_rules: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Auto-archive rules that meet high-confidence staleness criteria.

    Auto-archives if:
    - 0% adherence for 60+ days (rule_adherence tracked but never followed)
    - No references in 90+ days AND not modified in 90+ days
    - staleness_score >= 0.7

    Args:
        project_id: Project to archive rules for
        stale_rules: List of stale rules from check_rule_staleness()

    Returns:
        List of archived rule dicts with archive_path added
    """
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
        elif rule.get("last_referenced_days") is None and rule.get("last_modified_days", 0) > 90:
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
