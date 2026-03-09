"""Shared promotion policy for Explorer refactor findings.

The same evidence should drive both operator visibility in Explorer and
automatic task generation. This module keeps that policy in one place.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

_SIZE_ISSUES = frozenset({"oversized", "large_file", "bloat_critical", "bloat_warning"})
_STRONG_STRUCTURAL_ISSUES = frozenset(
    {
        "high_complexity",
        "deep_nesting",
        "has_long_functions",
        "too_many_functions",
        "too_many_classes",
        "has_large_classes",
    }
)
_HYGIENE_ISSUES = frozenset(
    {
        "magic_strings",
        "too_many_imports",
        "stale_todos",
        "deprecated_code",
        "legacy_code",
    }
)
_SMALL_SCOPE_MAX_LINES = 220
_HOTSPOT_HIGH = 200.0
_HOTSPOT_MEDIUM = 120.0
_COMMITS_HIGH = 5
_COMMITS_MEDIUM = 3


@dataclass(frozen=True)
class RefactorPromotionAssessment:
    """Promotion decision for one Explorer file target."""

    should_create_task: bool
    confidence: str
    structural_signals: int
    impact_signals: int
    promotion_score: int
    recommended_action: str
    promotion_reasons: list[str]
    suppression_reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize_issues(target: Mapping[str, Any]) -> set[str]:
    raw = target.get("refactor_issues")
    if isinstance(raw, list):
        return {str(issue) for issue in raw if issue}
    return set()


def _suppression_reasons(
    issues: set[str],
    lines: int,
    strong_structural: list[str],
    size_issues: list[str],
) -> list[str]:
    """Return suppression reasons for a finding (empty list = not suppressed)."""
    suppressions: list[str] = []
    if not strong_structural and size_issues:
        suppressions.append("Size-only finding without enough structural evidence")
    only_small_scope_hygiene = (
        lines <= _SMALL_SCOPE_MAX_LINES
        and not size_issues
        and not (issues & {"high_complexity", "medium_complexity", "deep_nesting"})
        and issues
        and issues <= (_HYGIENE_ISSUES | {"has_long_functions"})
    )
    if only_small_scope_hygiene:
        suppressions.append("Small-scope hygiene issue is better handled opportunistically")
    return suppressions


def _score_impact(
    strong_structural: list[str],
    hotspot: float,
    commits: int,
    has_tests: bool,
) -> tuple[int, int, list[str]]:
    """Return (impact_signals, impact_score_delta, reasons) for hotspot/commit/test signals."""
    impact_signals = 0
    score = 0
    reasons: list[str] = []

    if hotspot >= _HOTSPOT_HIGH:
        impact_signals += 1
        score += 2
        reasons.append(f"High hotspot score ({hotspot:.0f})")
    elif hotspot >= _HOTSPOT_MEDIUM:
        impact_signals += 1
        score += 1
        reasons.append(f"Meaningful hotspot score ({hotspot:.0f})")

    if commits >= _COMMITS_HIGH:
        impact_signals += 1
        score += 2
        reasons.append(f"Frequently edited recently ({commits} commits/90d)")
    elif commits >= _COMMITS_MEDIUM:
        impact_signals += 1
        score += 1
        reasons.append(f"Recent churn ({commits} commits/90d)")

    if not has_tests and (strong_structural or hotspot >= _HOTSPOT_MEDIUM):
        impact_signals += 1
        score += 1
        reasons.append("Nearby test coverage is missing")

    return impact_signals, score, reasons


def _compute_scores(
    issues: set[str],
    lines: int,
    complexity: float,
    hotspot: float,
    commits: int,
    has_tests: bool,
) -> tuple[int, int, int, list[str], list[str]]:
    """Return (structural_signals, impact_signals, promotion_score, reasons, suppressions)."""
    strong_structural = sorted(issues & _STRONG_STRUCTURAL_ISSUES)
    size_issues = sorted(issues & _SIZE_ISSUES)

    structural_signals = len(strong_structural) + min(len(size_issues), 1)
    score = 0
    reasons: list[str] = []

    if strong_structural:
        score += len(strong_structural) * 2
        reasons.append(
            "Structural pressure: "
            + ", ".join(issue.replace("_", " ") for issue in strong_structural[:3])
        )
    if size_issues and (complexity >= 12 or lines >= 500):
        score += 1
        reasons.append(f"Size pressure at {lines} LOC")

    impact_signals, impact_score, impact_reasons = _score_impact(
        strong_structural, hotspot, commits, has_tests
    )
    score += impact_score
    reasons.extend(impact_reasons)

    suppressions = _suppression_reasons(issues, lines, strong_structural, size_issues)
    return structural_signals, impact_signals, score, reasons, suppressions


def _decide_outcome(
    issues: set[str],
    strong_structural: list[str],
    impact_signals: int,
    promotion_score: int,
    hotspot: float,
    suppression_reasons: list[str],
    hygiene_issues: list[str],
    promotion_reasons: list[str],
) -> tuple[bool, str, str]:
    """Return (should_create_task, confidence, recommended_action)."""
    should_create_task = False
    if not suppression_reasons:
        should_create_task = (
            (len(strong_structural) >= 2)
            or (len(strong_structural) >= 1 and impact_signals >= 1)
            or ("high_complexity" in issues and hotspot >= _HOTSPOT_MEDIUM)
        )

    if should_create_task and promotion_score >= 6:
        confidence = "high"
    elif should_create_task:
        confidence = "medium"
    else:
        confidence = "low"

    if should_create_task:
        recommended_action = "create_task"
    elif suppression_reasons:
        recommended_action = "keep_in_explorer"
    else:
        recommended_action = "review_manually"
        if not promotion_reasons and hygiene_issues:
            promotion_reasons.append(
                "Observed hygiene issues: "
                + ", ".join(issue.replace("_", " ") for issue in hygiene_issues[:3])
            )

    return should_create_task, confidence, recommended_action


def assess_refactor_target(target: Mapping[str, Any]) -> RefactorPromotionAssessment:
    """Return whether a refactor finding is worth auto-promoting into a task."""
    issues = _normalize_issues(target)
    lines = int(target.get("lines_of_code") or 0)
    complexity = float(target.get("complexity_score") or 0.0)
    hotspot = float(target.get("hotspot_score") or 0.0)
    commits = int(target.get("commit_count_90d") or 0)
    has_tests = bool(target.get("test_file_exists"))

    structural_signals, impact_signals, promotion_score, promotion_reasons, suppression_reasons = (
        _compute_scores(issues, lines, complexity, hotspot, commits, has_tests)
    )

    strong_structural = sorted(issues & _STRONG_STRUCTURAL_ISSUES)
    hygiene_issues = sorted(issues & _HYGIENE_ISSUES)
    should_create_task, confidence, recommended_action = _decide_outcome(
        issues,
        strong_structural,
        impact_signals,
        promotion_score,
        hotspot,
        suppression_reasons,
        hygiene_issues,
        promotion_reasons,
    )

    return RefactorPromotionAssessment(
        should_create_task=should_create_task,
        confidence=confidence,
        structural_signals=structural_signals,
        impact_signals=impact_signals,
        promotion_score=promotion_score,
        recommended_action=recommended_action,
        promotion_reasons=promotion_reasons,
        suppression_reasons=suppression_reasons,
    )
