"""Tests for symbol ranking coverage guard in precision search."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from app.services.context_gatherer._precision_query import identifier_shaped_tokens
from app.services.context_gatherer._precision_ranking import search_and_rank_symbols


def _row(symbol_id: str, name: str, file_path: str) -> dict[str, Any]:
    return {
        "symbol_id": symbol_id,
        "name": name,
        "qualified_name": name,
        "file_path": file_path,
        "signature": f"def {name}()",
        "summary": "",
        "keywords": [],
    }


def _fake_search_symbols(rows_by_term: dict[str, list[dict[str, Any]]]):
    def fake(project_id: str, query: str, *, limit: int, path_prefix: str | None = None):
        return rows_by_term.get(query.lower(), [])

    return fake


class TestGenericOnlySuppression:
    def test_suppresses_candidates_when_every_identifier_token_missed(self) -> None:
        """20 'handler' hits for a nonexistent identifier are junk, not results."""
        rows_by_term = {
            "handler": [_row(f"s{i}", f"handler_{i}", f"src/file_{i}.py") for i in range(20)],
        }
        coverage: dict[str, object] = {}
        with patch(
            "app.services.context_gatherer._precision_ranking.search_symbols",
            side_effect=_fake_search_symbols(rows_by_term),
        ):
            result = search_and_rank_symbols(
                "project-1",
                ["resolve_search_timeout", "handler"],
                identifier_tokens=["resolve_search_timeout"],
                coverage=coverage,
            )

        assert result == []
        assert coverage["missed_identifier_tokens"] == ["resolve_search_timeout"]
        assert coverage["suppressed_generic_symbols"] == 20

    def test_keeps_results_when_one_identifier_token_hits(self) -> None:
        rows_by_term = {
            "scan_all_projects": [_row("s1", "scan_all_projects", "backend/app/tasks/explorer_tasks.py")],
            "handler": [_row("s2", "handler", "frontend/hooks/useMediaQuery.ts")],
        }
        coverage: dict[str, object] = {}
        with patch(
            "app.services.context_gatherer._precision_ranking.search_symbols",
            side_effect=_fake_search_symbols(rows_by_term),
        ):
            result = search_and_rank_symbols(
                "project-1",
                ["scan_all_projects", "missing_helper"],
                identifier_tokens=["scan_all_projects", "missing_helper"],
                coverage=coverage,
            )

        assert [r["name"] for r in result] == ["scan_all_projects"]
        assert coverage["missed_identifier_tokens"] == ["missing_helper"]
        assert coverage["suppressed_generic_symbols"] == 0

    def test_case_variant_hit_counts_as_identifier_coverage(self) -> None:
        """snake_case query matched via its CamelCase variant is covered, not missed."""
        rows_by_term = {
            "resolvesearchtimeout": [_row("s1", "ResolveSearchTimeout", "frontend/lib/search.ts")],
        }
        coverage: dict[str, object] = {}
        with patch(
            "app.services.context_gatherer._precision_ranking.search_symbols",
            side_effect=_fake_search_symbols(rows_by_term),
        ):
            result = search_and_rank_symbols(
                "project-1",
                ["resolve_search_timeout"],
                identifier_tokens=["resolve_search_timeout"],
                coverage=coverage,
            )

        assert [r["name"] for r in result] == ["ResolveSearchTimeout"]
        assert coverage["missed_identifier_tokens"] == []

    def test_no_identifier_tokens_keeps_generic_matches(self) -> None:
        """NL-style calls without identifier expectations keep weak-coverage hits."""
        rows_by_term = {
            "selector": [_row("s1", "ProjectSelector", "frontend/components/ProjectSelector.tsx")],
        }
        with patch(
            "app.services.context_gatherer._precision_ranking.search_symbols",
            side_effect=_fake_search_symbols(rows_by_term),
        ):
            result = search_and_rank_symbols("project-1", ["selector"])

        assert [r["name"] for r in result] == ["ProjectSelector"]

    def test_all_identifiers_missed_with_no_candidates_reports_missed_without_suppression(self) -> None:
        coverage: dict[str, object] = {}
        with patch(
            "app.services.context_gatherer._precision_ranking.search_symbols",
            return_value=[],
        ):
            result = search_and_rank_symbols(
                "project-1",
                ["scan_state_helper"],
                identifier_tokens=["scan_state_helper"],
                coverage=coverage,
            )

        assert result == []
        assert coverage["missed_identifier_tokens"] == ["scan_state_helper"]
        assert coverage["suppressed_generic_symbols"] == 0


class TestIdentifierShapedTokens:
    def test_extracts_snake_and_camel_tokens(self) -> None:
        assert identifier_shaped_tokens(["resolve_search_timeout handler"]) == ["resolve_search_timeout"]
        assert identifier_shaped_tokens(["ScanResultAggregator queue"]) == ["ScanResultAggregator"]

    def test_returns_empty_for_prose(self) -> None:
        assert identifier_shaped_tokens(["where is the project selector"]) == []

    def test_strips_punctuation_and_dedupes(self) -> None:
        assert identifier_shaped_tokens(["`scan_all_projects`", "scan_all_projects()"]) == ["scan_all_projects"]
