"""Tests for query classification helpers in _precision_query."""

from __future__ import annotations

from app.services.context_gatherer._precision_query import (
    expand_case_variants,
    extract_query_terms,
    has_path_segments,
    is_import_query,
    is_natural_language_query,
    is_short_or_generic,
    nl_to_symbol_terms,
    split_path_and_symbol_terms,
)
from app.services.context_gatherer._precision_ranking import symbol_match_rank as _symbol_match_rank


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
        name_match: dict[str, object] = {
            "name": "neo4j_cleanup",
            "qualified_name": "services.neo4j_cleanup",
            "signature": "def neo4j_cleanup()",
            "summary": "Cleans up graph data",
            "file_path": "backend/services/graph.py",
            "keywords": [],
        }
        summary_only: dict[str, object] = {
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
        exact: dict[str, object] = {
            "name": "neo4j",
            "qualified_name": "config.neo4j",
            "signature": "",
            "summary": "",
            "file_path": "backend/config.py",
            "keywords": [],
        }
        partial: dict[str, object] = {
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


class TestExpandCaseVariants:
    """CamelCase <-> snake_case normalization for query terms."""

    def test_camel_to_snake(self) -> None:
        assert "symbol_extractor" in expand_case_variants("SymbolExtractor")

    def test_snake_to_camel(self) -> None:
        assert "SymbolExtractor" in expand_case_variants("symbol_extractor")

    def test_preserves_original(self) -> None:
        variants = expand_case_variants("SymbolExtractor")
        assert "SymbolExtractor" in variants

    def test_single_word_unchanged(self) -> None:
        variants = expand_case_variants("Router")
        assert variants == ["Router"]

    def test_snake_single_word_unchanged(self) -> None:
        variants = expand_case_variants("router")
        assert variants == ["router"]

    def test_acronym_handling(self) -> None:
        variants = expand_case_variants("AgentHubLLMClient")
        assert "AgentHubLLMClient" in variants
        # Should produce a snake variant
        assert any("agent" in v and "hub" in v.lower() for v in variants)

    def test_test_prefix_module_name(self) -> None:
        variants = expand_case_variants("test_precision_query")
        assert "test_precision_query" in variants
        assert "TestPrecisionQuery" in variants


class TestIsImportQuery:
    """Detect 'import X' style queries that should route to text search."""

    def test_detects_import_statement(self) -> None:
        assert is_import_query(["import httpx"]) is True

    def test_detects_from_import(self) -> None:
        assert is_import_query(["from pathlib import Path"]) is True

    def test_rejects_symbol_with_import_substring(self) -> None:
        assert is_import_query(["import_plan_file"]) is False

    def test_rejects_normal_query(self) -> None:
        assert is_import_query(["TaskRouter"]) is False


class TestExtractQueryTermsWithVariants:
    """Verify that extract_query_terms produces case variants."""

    def test_camel_case_generates_snake_variant(self) -> None:
        terms = extract_query_terms(["SymbolExtractor"])
        lowered = [t.lower() for t in terms]
        assert "symbol_extractor" in lowered or "symbolextractor" in lowered

    def test_snake_case_generates_camel_variant(self) -> None:
        terms = extract_query_terms(["file_scanner"])
        assert any("FileScanner" in t for t in terms)


class TestIsNaturalLanguageQuery:
    """Detect plain English queries that should route to text search."""

    def test_detects_sql_ddl(self) -> None:
        assert is_natural_language_query(["CREATE TABLE explorer_symbols"]) is True
        assert is_natural_language_query(["SELECT id FROM tasks"]) is True
        assert is_natural_language_query(["ALTER TABLE explorer_entries"]) is True

    def test_detects_natural_language(self) -> None:
        assert is_natural_language_query(["scoring logic"]) is True
        assert is_natural_language_query(["search ranking algorithm"]) is True
        assert is_natural_language_query(["endpoint router mounting"]) is False  # "endpoint" is a code signal

    def test_rejects_code_identifiers(self) -> None:
        assert is_natural_language_query(["_search_symbol_matches"]) is False
        assert is_natural_language_query(["TaskOperationsMixin"]) is False
        assert is_natural_language_query(["search_symbols"]) is False

    def test_rejects_backtick_queries(self) -> None:
        assert is_natural_language_query(["`precision_search`"]) is False

    def test_rejects_single_word(self) -> None:
        # Single words aren't clearly natural language
        assert is_natural_language_query(["performance"]) is False

    def test_rejects_code_signal_queries(self) -> None:
        assert is_natural_language_query(["api endpoint routing"]) is False
        assert is_natural_language_query(["python class hierarchy"]) is False


class TestNlToSymbolTerms:
    """Generate potential symbol names from natural language query words."""

    def test_generates_camel_case(self) -> None:
        terms = nl_to_symbol_terms(["project selector"])
        assert "ProjectSelector" in terms

    def test_generates_snake_case(self) -> None:
        terms = nl_to_symbol_terms(["project selector"])
        assert "project_selector" in terms

    def test_includes_individual_words(self) -> None:
        terms = nl_to_symbol_terms(["project selector"])
        assert "project" in terms
        assert "selector" in terms

    def test_filters_stop_words(self) -> None:
        terms = nl_to_symbol_terms(["the project for this"])
        # "the", "for", "this" are stop words
        assert "project" in terms
        assert "the" not in terms

    def test_empty_after_stop_words(self) -> None:
        terms = nl_to_symbol_terms(["the and for"])
        assert terms == []

    def test_single_word(self) -> None:
        terms = nl_to_symbol_terms(["selector"])
        assert "selector" in terms

    def test_three_words(self) -> None:
        terms = nl_to_symbol_terms(["infra status bar"])
        assert "InfraStatusBar" in terms
        assert "infra_status_bar" in terms
