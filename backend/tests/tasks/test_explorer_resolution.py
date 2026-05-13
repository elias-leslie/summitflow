"""Tests for Explorer issue resolution."""

from __future__ import annotations

from app.tasks.explorer_resolution import _complexity_issue_still_exists


def test_complexity_resolution_does_not_use_target_lines_as_hard_gate() -> None:
    entry = {"metadata": {"complexity_score": 5, "lines_of_code": 301}}
    issue_metadata = {"target_lines": 300}

    assert _complexity_issue_still_exists(entry, issue_metadata) is False


def test_complexity_resolution_still_uses_complexity_threshold() -> None:
    entry = {"metadata": {"complexity_score": 12, "lines_of_code": 120}}

    assert _complexity_issue_still_exists(entry, {}) is True
