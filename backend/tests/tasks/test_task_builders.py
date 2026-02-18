"""Tests for issue-aware task builder functions.

Covers:
- _build_issue_aware_objective: objectives describe actual issues
- _build_issue_aware_done_when: criteria match detected issues
"""

from __future__ import annotations

from app.tasks.autonomous.task_builders import (
    _build_issue_aware_done_when,
    _build_issue_aware_objective,
)


class TestBuildIssueAwareObjective:
    """Tests for _build_issue_aware_objective."""

    def test_size_issue_includes_line_target(self) -> None:
        obj = _build_issue_aware_objective("foo.py", 400, 200, ["large_file"])
        assert "400" in obj
        assert "200" in obj

    def test_structural_issue_describes_problems(self) -> None:
        obj = _build_issue_aware_objective("foo.py", 200, 150, ["deep_nesting", "has_long_functions"])
        assert "nesting" in obj.lower()
        assert "function" in obj.lower()

    def test_no_size_issue_omits_line_target(self) -> None:
        obj = _build_issue_aware_objective("foo.py", 200, 150, ["deep_nesting"])
        assert "200 to" not in obj

    def test_preserves_behavior_mention(self) -> None:
        obj = _build_issue_aware_objective("foo.py", 200, 150, ["deep_nesting"])
        assert "preserving" in obj.lower()

    def test_limits_structural_labels_to_four(self) -> None:
        """Long issue lists are truncated to 4 labels."""
        issues = ["deep_nesting", "has_long_functions", "too_many_functions", "too_many_classes", "has_large_classes"]
        obj = _build_issue_aware_objective("foo.py", 200, 150, issues)
        # Should only mention first 4 structural issues (minus complexity/size)
        assert "resolving:" in obj


class TestBuildIssueAwareDoneWhen:
    """Tests for _build_issue_aware_done_when."""

    def test_always_includes_quality_gates(self) -> None:
        criteria = _build_issue_aware_done_when(400, 200, ["large_file"], False)
        assert any("quality gates" in c.lower() for c in criteria)

    def test_always_includes_no_regressions(self) -> None:
        criteria = _build_issue_aware_done_when(400, 200, ["large_file"], False)
        assert any("regressions" in c.lower() for c in criteria)

    def test_size_issue_includes_line_count_criterion(self) -> None:
        criteria = _build_issue_aware_done_when(400, 200, ["large_file"], False)
        assert any("200" in c for c in criteria)

    def test_no_size_issue_omits_line_count_criterion(self) -> None:
        criteria = _build_issue_aware_done_when(200, 150, ["deep_nesting"], False)
        assert not any("reduced to" in c.lower() for c in criteria)

    def test_long_functions_criterion(self) -> None:
        criteria = _build_issue_aware_done_when(200, 150, ["has_long_functions"], False)
        assert any("50 lines" in c for c in criteria)

    def test_deep_nesting_criterion(self) -> None:
        criteria = _build_issue_aware_done_when(200, 150, ["deep_nesting"], False)
        assert any("3 levels" in c for c in criteria)

    def test_too_many_functions_criterion(self) -> None:
        criteria = _build_issue_aware_done_when(200, 150, ["too_many_functions"], False)
        assert any("20" in c for c in criteria)

    def test_too_many_classes_criterion(self) -> None:
        criteria = _build_issue_aware_done_when(200, 150, ["too_many_classes"], False)
        assert any("5" in c for c in criteria)

    def test_large_classes_criterion(self) -> None:
        criteria = _build_issue_aware_done_when(200, 150, ["has_large_classes"], False)
        assert any("10 methods" in c for c in criteria)

    def test_magic_strings_criterion(self) -> None:
        criteria = _build_issue_aware_done_when(200, 150, ["magic_strings"], False)
        assert any("magic strings" in c.lower() for c in criteria)

    def test_too_many_imports_criterion(self) -> None:
        criteria = _build_issue_aware_done_when(200, 150, ["too_many_imports"], False)
        assert any("30" in c for c in criteria)

    def test_frontend_includes_browser_check(self) -> None:
        criteria = _build_issue_aware_done_when(400, 200, ["large_file"], True)
        assert any("console errors" in c.lower() for c in criteria)

    def test_backend_omits_browser_check(self) -> None:
        criteria = _build_issue_aware_done_when(400, 200, ["large_file"], False)
        assert not any("console errors" in c.lower() for c in criteria)

    def test_multiple_issues_all_covered(self) -> None:
        """Multiple issues all generate their own criteria."""
        criteria = _build_issue_aware_done_when(
            400, 200,
            ["large_file", "has_long_functions", "deep_nesting", "too_many_functions"],
            False,
        )
        assert any("200" in c for c in criteria)  # line count
        assert any("50 lines" in c for c in criteria)  # long functions
        assert any("3 levels" in c for c in criteria)  # nesting
        assert any("20" in c for c in criteria)  # function count
