"""Tests for task deduplication helpers.

Covers _extract_title_keywords, _calculate_keyword_overlap,
and duplicate_task_exists.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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

    def _mock_cursor(self, rows: list[tuple[str, str, str | None]]) -> MagicMock:
        """Create a mock cursor that returns given rows (id, title, description)."""
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
        cur = self._mock_cursor([("task-abc", "Fix login bug", None)])
        mock_get_conn.return_value = self._mock_connection(cur)

        result = duplicate_task_exists("proj", "Fix login bug")
        assert result == "task-abc"

    @patch("app.storage.tasks.dedup.get_connection")
    def test_near_duplicate_with_different_id(self, mock_get_conn: MagicMock) -> None:
        """Same title with different IDs matches when 3+ keywords survive filtering."""
        # "Fix backend scheduled execution handler 111" → {fix, backend, scheduled, execution, handler}
        cur = self._mock_cursor([("task-abc", "Fix backend scheduled execution handler 111", None)])
        mock_get_conn.return_value = self._mock_connection(cur)

        result = duplicate_task_exists("proj", "Fix backend scheduled execution handler 222")
        assert result == "task-abc"

    @patch("app.storage.tasks.dedup.get_connection")
    def test_different_title_no_match(self, mock_get_conn: MagicMock) -> None:
        cur = self._mock_cursor([("task-abc", "Fix login button styling", None)])
        mock_get_conn.return_value = self._mock_connection(cur)

        result = duplicate_task_exists("proj", "Add user authentication endpoint")
        assert result is None

    @patch("app.storage.tasks.dedup.get_connection")
    def test_excludes_self(self, mock_get_conn: MagicMock) -> None:
        """exclude_task_id is passed to SQL query to skip self."""
        cur = self._mock_cursor([])
        mock_get_conn.return_value = self._mock_connection(cur)

        duplicate_task_exists("proj", "Fix login button crash", exclude_task_id="task-self")

        sql = cur.execute.call_args[0][0]
        params = cur.execute.call_args[0][1]
        assert "id != %s" in sql
        assert "task-self" in params

    @patch("app.storage.tasks.dedup.get_connection")
    def test_no_exclude_when_none(self, mock_get_conn: MagicMock) -> None:
        """No exclude clause when exclude_task_id is None."""
        cur = self._mock_cursor([])
        mock_get_conn.return_value = self._mock_connection(cur)

        duplicate_task_exists("proj", "Fix login button crash", exclude_task_id=None)

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
        """Below 0.9 threshold should NOT match."""
        # "fix login bug" has keywords: {fix, login, bug}
        # "fix login styling" has keywords: {fix, login, styling}
        # overlap: {fix, login} / {fix, login, bug, styling} = 2/4 = 0.5
        cur = self._mock_cursor([("task-abc", "Fix login styling", None)])
        mock_get_conn.return_value = self._mock_connection(cur)

        result = duplicate_task_exists("proj", "Fix login bug")
        assert result is None

    @patch("app.storage.tasks.dedup.get_connection")
    def test_old_threshold_no_longer_matches(self, mock_get_conn: MagicMock) -> None:
        """0.8 overlap should NOT match with stricter 0.9 threshold."""
        # kw1 = {alpha, beta, gamma, delta} kw2 = {alpha, beta, gamma, delta, zeta}
        # overlap = 4/5 = 0.8 — below new 0.9 threshold
        cur = self._mock_cursor([("task-abc", "alpha beta gamma delta zeta", None)])
        mock_get_conn.return_value = self._mock_connection(cur)

        result = duplicate_task_exists("proj", "alpha beta gamma delta")
        assert result is None

    @patch("app.storage.tasks.dedup.get_connection")
    def test_threshold_at_0_9(self, mock_get_conn: MagicMock) -> None:
        """At 0.9+ threshold should match."""
        # kw1 = {alpha, beta, gamma, delta, epsilon, zeta, eta, kappa, lambda_}
        # kw2 = {alpha, beta, gamma, delta, epsilon, zeta, eta, kappa, lambda_, mu}
        # overlap = 9/10 = 0.9 ✓
        cur = self._mock_cursor([(
            "task-abc",
            "alpha beta gamma delta epsilon zeta eta kappa lambda mu",
            None,
        )])
        mock_get_conn.return_value = self._mock_connection(cur)

        result = duplicate_task_exists(
            "proj", "alpha beta gamma delta epsilon zeta eta kappa lambda"
        )
        assert result == "task-abc"

    @patch("app.storage.tasks.dedup.get_connection")
    def test_insufficient_keywords_skips_dedup(self, mock_get_conn: MagicMock) -> None:
        """Titles that collapse to <3 keywords after filtering skip dedup entirely.

        This prevents false positives from titles like "AutoTest: Scheduled exec 111"
        where noise stripping leaves only 2 keywords.
        """
        cur = self._mock_cursor([("task-abc", "AutoTest: Scheduled execution 111111", None)])
        mock_get_conn.return_value = self._mock_connection(cur)

        result = duplicate_task_exists("proj", "AutoTest: Scheduled execution 222222")
        assert result is None
        # Should not query DB when new title has insufficient keywords
        mock_get_conn.assert_not_called()

    @patch("app.storage.tasks.dedup.get_connection")
    def test_sufficient_keywords_still_dedupes(self, mock_get_conn: MagicMock) -> None:
        """Titles with 3+ keywords after filtering are still deduped normally."""
        # "fix login button crash" → {fix, login, button, crash} = 4 keywords
        cur = self._mock_cursor([("task-abc", "Fix login button crash", None)])
        mock_get_conn.return_value = self._mock_connection(cur)

        result = duplicate_task_exists("proj", "Fix login button crash")
        assert result == "task-abc"

    @patch("app.storage.tasks.dedup.get_connection")
    def test_picks_first_duplicate(self, mock_get_conn: MagicMock) -> None:
        """Returns the first matching duplicate's ID."""
        cur = self._mock_cursor([
            ("task-1", "Completely different title here", None),
            ("task-2", "Fix login button crash", None),
            ("task-3", "Fix login button crash again", None),
        ])
        mock_get_conn.return_value = self._mock_connection(cur)

        result = duplicate_task_exists("proj", "Fix login button crash")
        assert result == "task-2"

    @patch("app.storage.tasks.dedup.get_connection")
    def test_same_title_different_description_no_match(
        self, mock_get_conn: MagicMock
    ) -> None:
        """Same title but different descriptions should NOT match when description provided."""
        # Title overlap = 1.0, but description overlap < 0.5
        cur = self._mock_cursor([(
            "task-abc",
            "Refactor authentication system",
            "Move from JWT to OAuth provider integration",
        )])
        mock_get_conn.return_value = self._mock_connection(cur)

        result = duplicate_task_exists(
            "proj",
            "Refactor authentication system",
            description="Add two-factor authentication with TOTP support",
        )
        assert result is None

    @patch("app.storage.tasks.dedup.get_connection")
    def test_same_title_same_description_matches(
        self, mock_get_conn: MagicMock
    ) -> None:
        """Same title and similar description should match."""
        cur = self._mock_cursor([(
            "task-abc",
            "Refactor authentication system",
            "Move from JWT tokens to OAuth provider integration",
        )])
        mock_get_conn.return_value = self._mock_connection(cur)

        result = duplicate_task_exists(
            "proj",
            "Refactor authentication system",
            description="Move from JWT tokens to OAuth provider",
        )
        assert result == "task-abc"

    @patch("app.storage.tasks.dedup.get_connection")
    def test_no_description_falls_back_to_title_only(
        self, mock_get_conn: MagicMock
    ) -> None:
        """When no description provided, only title matching is used."""
        cur = self._mock_cursor([(
            "task-abc",
            "Fix login button crash",
            "Some existing description",
        )])
        mock_get_conn.return_value = self._mock_connection(cur)

        result = duplicate_task_exists("proj", "Fix login button crash")
        assert result == "task-abc"
