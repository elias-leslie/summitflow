"""Tests for query classification helpers in _precision_query."""

from __future__ import annotations

from app.services.context_gatherer._precision_query import (
    has_path_segments,
    is_short_or_generic,
    split_path_and_symbol_terms,
)
from app.services.context_gatherer.precision_code_search import _symbol_match_rank


class TestHasPathSegments:
    def test_detects_slash_paths(self) -> None:
        assert has_path_segments(["Show Preview frontend/src"]) is True

    def test_detects_file_extensions(self) -> None:
        assert has_path_segments(["explorer.py"]) is True
        assert has_path_segments(["component.tsx"]) is True

    def test_rejects_pure_symbol_queries(self) -> None:
        assert has_path_segments(["collect_precision_code_search_context"]) is False

    def test_rejects_camel_case_symbols(self) -> None:
        assert has_path_segments(["TaskOperationsMixin"]) is False


class TestIsShortOrGeneric:
    def test_detects_short_acronyms(self) -> None:
        assert is_short_or_generic(["dnd"]) is True
        assert is_short_or_generic(["ui"]) is True

    def test_detects_single_generic_word(self) -> None:
        assert is_short_or_generic(["mode"]) is True
        assert is_short_or_generic(["status"]) is True

    def test_rejects_specific_identifiers(self) -> None:
        assert is_short_or_generic(["collect_precision_code_search_context"]) is False
        assert is_short_or_generic(["TaskOperationsMixin"]) is False

    def test_rejects_multi_word_specific_queries(self) -> None:
        assert is_short_or_generic(["campaign mode handler"]) is False

    def test_detects_all_short_terms(self) -> None:
        assert is_short_or_generic(["dnd ui"]) is True

    def test_empty_query_is_generic(self) -> None:
        assert is_short_or_generic([""]) is True


class TestSplitPathAndSymbolTerms:
    def test_separates_path_from_symbols(self) -> None:
        paths, symbols = split_path_and_symbol_terms(["Show Preview frontend/src"])
        assert "frontend/src" in paths
        assert "Show" in symbols
        assert "Preview" in symbols

    def test_detects_file_extensions_as_paths(self) -> None:
        paths, symbols = split_path_and_symbol_terms(["explorer.py utils"])
        assert "explorer.py" in paths
        assert "utils" in symbols

    def test_pure_symbol_query_has_no_paths(self) -> None:
        paths, symbols = split_path_and_symbol_terms(["TaskOperationsMixin"])
        assert paths == []
        assert "TaskOperationsMixin" in symbols

    def test_pure_path_query_has_no_symbols(self) -> None:
        paths, symbols = split_path_and_symbol_terms(["backend/app/api/explorer.py"])
        assert "backend/app/api/explorer.py" in paths
        assert symbols == []

    def test_multiple_queries_combined(self) -> None:
        paths, symbols = split_path_and_symbol_terms(["search_symbols", "storage/explorer.py"])
        assert "storage/explorer.py" in paths
        assert "search_symbols" in symbols


class TestSymbolMatchRank:
    """Verify ranking prioritizes name/qualified_name over incidental summary mentions."""

    def test_name_match_ranks_above_summary_only(self) -> None:
        """A symbol with query in its name should outrank one with query only in summary."""
        name_match = {
            "name": "neo4j_cleanup",
            "qualified_name": "services.neo4j_cleanup",
            "signature": "def neo4j_cleanup()",
            "summary": "Cleans up graph data",
            "file_path": "backend/services/graph.py",
            "keywords": [],
        }
        summary_only = {
            "name": "scan_entries",
            "qualified_name": "services.scan_entries",
            "signature": "def scan_entries()",
            "summary": "Scans all entries including neo4j graph nodes",
            "file_path": "backend/services/scanner.py",
            "keywords": ["neo4j"],
        }

        queries = ["neo4j"]
        terms = ["neo4j"]
        rank_name = _symbol_match_rank(name_match, queries, terms)
        rank_summary = _symbol_match_rank(summary_only, queries, terms)
        assert rank_name > rank_summary, "Name match should rank higher than summary-only match"

    def test_exact_name_ranks_above_partial(self) -> None:
        exact = {
            "name": "neo4j",
            "qualified_name": "config.neo4j",
            "signature": "",
            "summary": "",
            "file_path": "backend/config.py",
            "keywords": [],
        }
        partial = {
            "name": "neo4j_cleanup",
            "qualified_name": "services.neo4j_cleanup",
            "signature": "",
            "summary": "",
            "file_path": "backend/services/graph.py",
            "keywords": [],
        }

        queries = ["neo4j"]
        terms = ["neo4j"]
        rank_exact = _symbol_match_rank(exact, queries, terms)
        rank_partial = _symbol_match_rank(partial, queries, terms)
        assert rank_exact > rank_partial, "Exact name match should rank higher than partial"
