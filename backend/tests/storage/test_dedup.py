"""Tests for task deduplication helpers.

Covers _extract_title_keywords, _calculate_keyword_overlap,
and duplicate_task_exists.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.storage.tasks.dedup import (
    _calculate_keyword_overlap,
    _extract_title_keywords,
    duplicate_task_exists,
)


class TestExtractTitleKeywords:
    """Tests for _extract_title_keywords."""

    def test_basic_title(self) -> None:
        result = _extract_title_keywords("Fix login button not responding")
        assert "fix" in result
        assert "login" in result
        assert "button" in result
        assert "responding" in result
        # "not" is <3 chars, excluded
        assert "not" not in result

    def test_strips_hex_ids(self) -> None:
        """Hex tokens (8+ chars) are noise — stripped."""
        result = _extract_title_keywords("AutoTest-Phase4: Scheduled exec 1770765896")
        assert "scheduled" in result
        assert "exec" in result
        # 1770765896 is pure digits — stripped
        assert "1770765896" not in result

    def test_strips_pure_numbers(self) -> None:
        result = _extract_title_keywords("P4-sched-997e3281: Verify Hatchet dispatch")
        assert "verify" in result
        assert "hatchet" in result
        assert "dispatch" in result
        # 997e3281 is hex — stripped
        assert "997e3281" not in result

    def test_stops_words_removed(self) -> None:
        result = _extract_title_keywords("the task for this test and that thing")
        assert "the" not in result
        assert "and" not in result
        assert "for" not in result
        assert "this" not in result
        assert "that" not in result
        assert "task" not in result
        assert "test" not in result

    def test_case_insensitive(self) -> None:
        result = _extract_title_keywords("Fix Login BUTTON")
        assert "fix" in result
        assert "login" in result
        assert "button" in result

    def test_empty_title(self) -> None:
        assert _extract_title_keywords("") == set()

    def test_only_noise(self) -> None:
        """Title with only IDs/numbers/stop words produces empty set."""
        result = _extract_title_keywords("12345 abcdef12 the and")
        assert result == set()

    def test_uuid_stripped(self) -> None:
        result = _extract_title_keywords("Fix bug in task-a1b2c3d4e5f6")
        assert "bug" in result
        assert "a1b2c3d4e5f6" not in result

    def test_similar_titles_same_keywords(self) -> None:
        """Two runs of the same test should produce identical keywords."""
        kw1 = _extract_title_keywords("AutoTest: Scheduled execution 111111")
        kw2 = _extract_title_keywords("AutoTest: Scheduled execution 222222")
        assert kw1 == kw2

    def test_different_titles_different_keywords(self) -> None:
        kw1 = _extract_title_keywords("Fix login button styling")
        kw2 = _extract_title_keywords("Add user authentication endpoint")
        assert kw1 != kw2


class TestCalculateKeywordOverlap:
    """Tests for _calculate_keyword_overlap (Jaccard similarity)."""

    def test_identical_sets(self) -> None:
        assert _calculate_keyword_overlap({"a", "b", "c"}, {"a", "b", "c"}) == 1.0

    def test_disjoint_sets(self) -> None:
        assert _calculate_keyword_overlap({"a", "b"}, {"c", "d"}) == 0.0

    def test_partial_overlap(self) -> None:
        # {a,b,c} & {b,c,d} = {b,c}, union = {a,b,c,d} → 2/4 = 0.5
        assert _calculate_keyword_overlap({"a", "b", "c"}, {"b", "c", "d"}) == 0.5

    def test_empty_set(self) -> None:
        assert _calculate_keyword_overlap(set(), {"a"}) == 0.0
        assert _calculate_keyword_overlap({"a"}, set()) == 0.0

    def test_both_empty(self) -> None:
        assert _calculate_keyword_overlap(set(), set()) == 0.0


class TestDuplicateTaskExists:
    """Tests for duplicate_task_exists with mocked DB."""

    def _mock_cursor(self, rows: list[tuple[str, str]]) -> MagicMock:
        """Create a mock cursor that returns given rows."""
        cur = MagicMock()
        cur.fetchall.return_value = rows
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        return cur

    def _mock_connection(self, cursor: MagicMock) -> MagicMock:
        conn = MagicMock()
        conn.cursor.return_value = cursor
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        return conn

    @patch("app.storage.tasks.dedup.get_connection")
    def test_no_existing_tasks(self, mock_get_conn: MagicMock) -> None:
        cur = self._mock_cursor([])
        mock_get_conn.return_value = self._mock_connection(cur)

        result = duplicate_task_exists("proj", "Fix login bug")
        assert result is None

    @patch("app.storage.tasks.dedup.get_connection")
    def test_exact_duplicate_found(self, mock_get_conn: MagicMock) -> None:
        """Identical title should match."""
        cur = self._mock_cursor([("task-abc", "Fix login bug")])
        mock_get_conn.return_value = self._mock_connection(cur)

        result = duplicate_task_exists("proj", "Fix login bug")
        assert result == "task-abc"

    @patch("app.storage.tasks.dedup.get_connection")
    def test_near_duplicate_with_different_id(self, mock_get_conn: MagicMock) -> None:
        """Same title but different appended IDs should match."""
        cur = self._mock_cursor([("task-abc", "AutoTest: Scheduled execution 111111")])
        mock_get_conn.return_value = self._mock_connection(cur)

        result = duplicate_task_exists("proj", "AutoTest: Scheduled execution 222222")
        assert result == "task-abc"

    @patch("app.storage.tasks.dedup.get_connection")
    def test_different_title_no_match(self, mock_get_conn: MagicMock) -> None:
        cur = self._mock_cursor([("task-abc", "Fix login button styling")])
        mock_get_conn.return_value = self._mock_connection(cur)

        result = duplicate_task_exists("proj", "Add user authentication endpoint")
        assert result is None

    @patch("app.storage.tasks.dedup.get_connection")
    def test_excludes_self(self, mock_get_conn: MagicMock) -> None:
        """exclude_task_id is passed to SQL query to skip self."""
        cur = self._mock_cursor([])
        mock_get_conn.return_value = self._mock_connection(cur)

        duplicate_task_exists("proj", "Fix bug", exclude_task_id="task-self")

        sql = cur.execute.call_args[0][0]
        params = cur.execute.call_args[0][1]
        assert "id != %s" in sql
        assert "task-self" in params

    @patch("app.storage.tasks.dedup.get_connection")
    def test_no_exclude_when_none(self, mock_get_conn: MagicMock) -> None:
        """No exclude clause when exclude_task_id is None."""
        cur = self._mock_cursor([])
        mock_get_conn.return_value = self._mock_connection(cur)

        duplicate_task_exists("proj", "Fix bug", exclude_task_id=None)

        sql = cur.execute.call_args[0][0]
        assert "id != %s" not in sql

    @patch("app.storage.tasks.dedup.get_connection")
    def test_empty_title_returns_none(self, mock_get_conn: MagicMock) -> None:
        """Empty title has no keywords — can't be a duplicate."""
        result = duplicate_task_exists("proj", "")
        assert result is None
        # Should not even query DB
        mock_get_conn.assert_not_called()

    @patch("app.storage.tasks.dedup.get_connection")
    def test_threshold_boundary_below(self, mock_get_conn: MagicMock) -> None:
        """Just below 0.8 threshold should NOT match."""
        # "fix login bug" has keywords: {fix, login, bug}
        # "fix login styling" has keywords: {fix, login, styling}
        # overlap: {fix, login} / {fix, login, bug, styling} = 2/4 = 0.5
        cur = self._mock_cursor([("task-abc", "Fix login styling")])
        mock_get_conn.return_value = self._mock_connection(cur)

        result = duplicate_task_exists("proj", "Fix login bug")
        assert result is None

    @patch("app.storage.tasks.dedup.get_connection")
    def test_threshold_boundary_at(self, mock_get_conn: MagicMock) -> None:
        """At exactly 0.8 threshold should match."""
        # {scheduled, execution, hatchet, cron, dispatch} vs
        # {scheduled, execution, hatchet, cron, verify}
        # overlap: 4/6 = 0.667 — not enough
        # Let me make a better example:
        # "fix login button crash" → {fix, login, button, crash}
        # "fix login button error" → {fix, login, button}  (error is stop word)
        # overlap: {fix, login, button} / {fix, login, button, crash} = 3/4 = 0.75 — still below
        # Need 4/5 = 0.8:
        # "fix login button crash mobile" → {fix, login, button, crash, mobile}
        # "fix login button crash tablet" → {fix, login, button, crash, tablet}
        # overlap: {fix, login, button, crash} / {fix, login, button, crash, mobile, tablet} = 4/6 = 0.667
        # Hmm. Let me try:
        # "add user auth endpoint handler" → {add, user, auth, endpoint, handler}  wait, "add" is NOT a stop word here
        # Actually let me just make it work with 4/5:
        # kw1 = {alpha, beta, gamma, delta, epsilon}
        # kw2 = {alpha, beta, gamma, delta, zeta}
        # overlap = 4/6 = 0.667
        # For exactly 0.8 I need 4/5: share 4 of 5 total unique keywords
        # kw1 = {alpha, beta, gamma, delta}
        # kw2 = {alpha, beta, gamma, zeta}
        # overlap = 3/5 = 0.6
        # For 0.8: need intersection/union = 0.8 → 4/(4+1) = 4/5
        # kw1 = {alpha, beta, gamma, delta} kw2 = {alpha, beta, gamma, delta, zeta}
        # overlap = 4/5 = 0.8 ✓
        cur = self._mock_cursor([("task-abc", "alpha beta gamma delta zeta")])
        mock_get_conn.return_value = self._mock_connection(cur)

        result = duplicate_task_exists("proj", "alpha beta gamma delta")
        assert result == "task-abc"

    @patch("app.storage.tasks.dedup.get_connection")
    def test_picks_first_duplicate(self, mock_get_conn: MagicMock) -> None:
        """Returns the first matching duplicate's ID."""
        cur = self._mock_cursor([
            ("task-1", "Completely different title here"),
            ("task-2", "Fix login button crash"),
            ("task-3", "Fix login button crash again"),
        ])
        mock_get_conn.return_value = self._mock_connection(cur)

        result = duplicate_task_exists("proj", "Fix login button crash")
        assert result == "task-2"
