"""Tests for file_complexity module - priority calculation and issue detection.

Covers:
- calculate_refactor_priority with health_flags and bloat_level
- build_refactor_issues comprehensive issue detection
"""

from __future__ import annotations

from app.services.explorer.types.file_complexity import (
    build_refactor_issues,
    calculate_refactor_priority,
)


class TestCalculateRefactorPriority:
    """Tests for expanded calculate_refactor_priority."""

    # --- Original complexity/LOC thresholds still work ---

    def test_high_complexity_returns_high(self) -> None:
        assert calculate_refactor_priority(16.0, 100) == "high"

    def test_high_lines_returns_high(self) -> None:
        assert calculate_refactor_priority(5.0, 501) == "high"

    def test_medium_complexity_returns_medium(self) -> None:
        assert calculate_refactor_priority(11.0, 100) == "medium"

    def test_medium_lines_returns_medium(self) -> None:
        assert calculate_refactor_priority(5.0, 301) == "medium"

    def test_below_thresholds_returns_none(self) -> None:
        assert calculate_refactor_priority(5.0, 100) == "none"

    # --- Health flags promote priority ---

    def test_single_health_flag_no_longer_promotes_by_itself(self) -> None:
        flags = {"deep_nesting": True}
        assert calculate_refactor_priority(5.0, 100, health_flags=flags) == "none"

    def test_two_health_flags_promotes_to_medium(self) -> None:
        flags = {"deep_nesting": True, "has_long_functions": True}
        assert calculate_refactor_priority(5.0, 100, health_flags=flags) == "medium"

    def test_three_health_flags_promotes_to_high(self) -> None:
        flags = {"deep_nesting": True, "has_long_functions": True, "too_many_functions": True}
        assert calculate_refactor_priority(5.0, 100, health_flags=flags) == "high"

    def test_empty_health_flags_no_effect(self) -> None:
        assert calculate_refactor_priority(5.0, 100, health_flags={}) == "none"

    def test_none_health_flags_no_effect(self) -> None:
        assert calculate_refactor_priority(5.0, 100, health_flags=None) == "none"

    # --- Bloat level promotes priority ---

    def test_bloat_critical_promotes_to_high(self) -> None:
        assert calculate_refactor_priority(5.0, 100, bloat_level="critical") == "high"

    def test_bloat_warning_promotes_to_medium(self) -> None:
        assert calculate_refactor_priority(5.0, 100, bloat_level="warning") == "medium"

    def test_bloat_ok_no_effect(self) -> None:
        assert calculate_refactor_priority(5.0, 100, bloat_level="ok") == "none"

    # --- Combined dimensions ---

    def test_health_flags_and_bloat_combined(self) -> None:
        flags = {"deep_nesting": True}
        # bloat_warning alone = medium, single flag alone = none
        # combined should still be medium
        assert calculate_refactor_priority(5.0, 100, health_flags=flags, bloat_level="warning") == "medium"

    def test_complexity_threshold_exact_boundary(self) -> None:
        """At exactly the threshold, should not trigger (> not >=)."""
        assert calculate_refactor_priority(15.0, 100) != "high"
        assert calculate_refactor_priority(10.0, 100) != "medium"


class TestBuildRefactorIssues:
    """Tests for build_refactor_issues comprehensive issue detection."""

    def test_high_complexity_issue(self) -> None:
        issues = build_refactor_issues(16.0, 100)
        assert "high_complexity" in issues

    def test_medium_complexity_issue(self) -> None:
        issues = build_refactor_issues(11.0, 100)
        assert "medium_complexity" in issues
        assert "high_complexity" not in issues

    def test_oversized_issue(self) -> None:
        issues = build_refactor_issues(5.0, 501)
        assert "oversized" in issues

    def test_large_file_issue(self) -> None:
        issues = build_refactor_issues(5.0, 301)
        assert "large_file" in issues
        assert "oversized" not in issues

    def test_bloat_critical_issue(self) -> None:
        issues = build_refactor_issues(5.0, 100, bloat_level="critical")
        assert "bloat_critical" in issues

    def test_bloat_warning_issue(self) -> None:
        issues = build_refactor_issues(5.0, 100, bloat_level="warning")
        assert "bloat_warning" in issues

    def test_health_flags_become_issues(self) -> None:
        flags = {"deep_nesting": True, "has_long_functions": True}
        issues = build_refactor_issues(5.0, 100, health_flags=flags)
        assert "deep_nesting" in issues
        assert "has_long_functions" in issues

    def test_magic_strings_issue(self) -> None:
        magic = {"hardcoded_urls": 3}
        issues = build_refactor_issues(5.0, 100, magic_strings=magic)
        assert "magic_strings" in issues

    def test_compat_cruft_stale_todos(self) -> None:
        cruft = {"stale_todos": 5}
        issues = build_refactor_issues(5.0, 100, compat_cruft=cruft)
        assert "stale_todos" in issues

    def test_compat_cruft_deprecated(self) -> None:
        cruft = {"deprecated_markers": 2}
        issues = build_refactor_issues(5.0, 100, compat_cruft=cruft)
        assert "deprecated_code" in issues

    def test_compat_cruft_legacy(self) -> None:
        cruft = {"legacy_vars": 1}
        issues = build_refactor_issues(5.0, 100, compat_cruft=cruft)
        assert "legacy_code" in issues

    def test_no_issues_returns_empty(self) -> None:
        issues = build_refactor_issues(5.0, 100)
        assert issues == []

    def test_all_dimensions_combined(self) -> None:
        """File with issues across all categories."""
        issues = build_refactor_issues(
            16.0, 501,
            health_flags={"deep_nesting": True, "has_long_functions": True},
            bloat_level="critical",
            magic_strings={"hardcoded_urls": 1},
            compat_cruft={"stale_todos": 3, "deprecated_markers": 1},
        )
        assert "high_complexity" in issues
        assert "oversized" in issues
        assert "bloat_critical" in issues
        assert "deep_nesting" in issues
        assert "has_long_functions" in issues
        assert "magic_strings" in issues
        assert "stale_todos" in issues
        assert "deprecated_code" in issues
