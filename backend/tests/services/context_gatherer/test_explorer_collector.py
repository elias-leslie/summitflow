"""Tests for explorer-backed context gathering."""

from __future__ import annotations

from unittest.mock import patch

from app.services.context_gatherer.explorer_collector import gather_explorer_context
from app.services.context_gatherer.precision_code_search import (
    collect_precision_code_search_context,
)


def test_gather_explorer_context_includes_symbol_matches() -> None:
    """Relevant symbol matches should be included ahead of broader file listings."""
    expected = "Precision Code Search: symbol-first\n\n## Relevant Symbols\n\n- `get_file_tree` ..."
    with patch(
        "app.services.context_gatherer.explorer_collector.collect_precision_code_search_context"
    ) as mock_collect:
        mock_collect.return_value.prompt_context = expected
        context = gather_explorer_context("project-1", "get_file_tree")

    mock_collect.assert_called_once()
    assert "Precision Code Search: symbol-first" in context
    assert "## Relevant Symbols" in context
    assert "`get_file_tree`" in context


def test_collect_precision_code_search_context_tracks_token_savings() -> None:
    with (
        patch("app.services.context_gatherer.precision_code_search.search_symbols") as mock_search,
        patch(
            "app.services.context_gatherer.precision_code_search.list_related_entries_for_file"
        ) as mock_related,
        patch("app.services.context_gatherer.precision_code_search.get_entries") as mock_entries,
        patch("app.services.context_gatherer.precision_code_search.get_symbol") as mock_get_symbol,
        patch(
            "app.services.context_gatherer.precision_code_search._estimate_naive_file_tokens_for_symbols",
            return_value=2000,
        ),
        patch(
            "app.services.context_gatherer.precision_code_search._read_symbol_source"
        ) as mock_read_symbol_source,
    ):
        mock_search.return_value = [
            {
                "symbol_id": "backend/app/api/files.py::get_file_tree#function",
                "qualified_name": "get_file_tree",
                "name": "get_file_tree",
                "kind": "function",
                "file_path": "backend/app/api/files.py",
                "start_line": 7,
                "end_line": 9,
                "signature": "def get_file_tree(path: str) -> dict[str, str]",
                "summary": "List directory entries for file tree navigation.",
            }
        ]
        mock_related.return_value = []
        mock_get_symbol.return_value = {
            "symbol_id": "backend/app/api/files.py::get_file_tree#function",
            "qualified_name": "get_file_tree",
            "file_path": "backend/app/api/files.py",
            "start_line": 7,
            "end_line": 9,
        }
        mock_read_symbol_source.return_value = "def get_file_tree(path: str) -> dict[str, str]: ..."
        mock_entries.side_effect = [
            [{"path": "backend/app/api/files.py", "name": "files.py"}],
            [{"path": "GET /files/tree", "metadata": {"method": "GET"}}],
            [{"name": "files"}],
        ]

        result = collect_precision_code_search_context("project-1", ["get_file_tree"])

    assert result.metadata["used_symbol_first"]
    assert result.metadata["symbol_count"] == 1
    assert result.metadata["naive_file_tokens"] == 2000
    assert result.metadata["estimated_tokens_saved"] > 0
    assert "Exact Source Slices" in result.prompt_context


def test_collect_precision_code_search_context_skips_workflow_meta_queries() -> None:
    result = collect_precision_code_search_context(
        "project-1",
        [
            "Run one no-code autonomous validation task through the updated workflow and confirm it no longer fails on missing work product or irrelevant Precision Code Search injection."
        ],
    )

    assert result.prompt_context == ""
    assert result.metadata["skipped_reason"] == "workflow_meta_low_signal"


def test_collect_precision_code_search_context_filters_fallback_entries_by_query_terms() -> None:
    with (
        patch("app.services.context_gatherer.precision_code_search.search_symbols", return_value=[]),
        patch("app.services.context_gatherer.precision_code_search.get_entries") as mock_entries,
    ):
        mock_entries.side_effect = [
            [
                {"path": "backend/app/api/tasks.py", "name": "tasks.py"},
                {"path": "frontend/components/home.tsx", "name": "home.tsx"},
            ],
            [
                {"path": "/api/tasks", "name": "tasks", "metadata": {"method": "GET"}},
                {"path": "/api/users", "name": "users", "metadata": {"method": "GET"}},
            ],
            [
                {"name": "tasks"},
                {"name": "users"},
            ],
        ]

        result = collect_precision_code_search_context("project-1", ["tasks api"])

    assert "backend/app/api/tasks.py" in result.prompt_context
    assert "/api/tasks" in result.prompt_context
    assert "- tasks" in result.prompt_context
    assert "/api/users" not in result.prompt_context
    assert "- users" not in result.prompt_context


def test_collect_precision_code_search_context_skips_fallback_fetch_on_symbol_hits() -> None:
    with (
        patch(
            "app.services.context_gatherer.precision_code_search.search_symbols",
            return_value=[
                {
                    "symbol_id": "backend/app/api/files.py::get_file_tree#function",
                    "qualified_name": "get_file_tree",
                    "name": "get_file_tree",
                    "kind": "function",
                    "file_path": "backend/app/api/files.py",
                    "start_line": 7,
                    "end_line": 9,
                    "signature": "def get_file_tree(path: str) -> dict[str, str]",
                    "summary": "List directory entries for file tree navigation.",
                }
            ],
        ),
        patch(
            "app.services.context_gatherer.precision_code_search.list_related_entries_for_file",
            return_value=[],
        ),
        patch(
            "app.services.context_gatherer.precision_code_search.get_symbol",
            return_value={
                "symbol_id": "backend/app/api/files.py::get_file_tree#function",
                "qualified_name": "get_file_tree",
                "file_path": "backend/app/api/files.py",
                "start_line": 7,
                "end_line": 9,
            },
        ),
        patch(
            "app.services.context_gatherer.precision_code_search._read_symbol_source",
            return_value="def get_file_tree(path: str) -> dict[str, str]: ...",
        ),
        patch(
            "app.services.context_gatherer.precision_code_search._estimate_naive_file_tokens_for_symbols",
            return_value=2000,
        ),
        patch("app.services.context_gatherer.precision_code_search.get_entries") as mock_entries,
    ):
        result = collect_precision_code_search_context("project-1", ["get_file_tree"])

    mock_entries.assert_not_called()
    assert result.metadata["used_symbol_first"]
    assert not result.metadata["used_fallback"]


def test_collect_precision_code_search_context_refreshes_stale_file_index() -> None:
    with (
        patch(
            "app.services.context_gatherer.precision_code_search.explorer_service.get_stats",
            return_value={"total": 12, "last_scanned": "2026-03-10T17:00:00+00:00"},
        ),
        patch(
            "app.services.context_gatherer.precision_code_search.get_symbol_stats",
            return_value={"count": 4, "last_updated": "2026-03-10T17:00:00+00:00"},
        ),
        patch(
            "app.services.context_gatherer.precision_code_search.explorer_service.scan"
        ) as mock_scan,
        patch(
            "app.services.context_gatherer.precision_code_search.search_symbols",
            return_value=[],
        ),
        patch(
            "app.services.context_gatherer.precision_code_search.get_entries",
            return_value=[],
        ),
    ):
        mock_scan.return_value.success = True
        mock_scan.return_value.entries_found = 12
        mock_scan.return_value.entries_saved = 12
        mock_scan.return_value.duration_ms = 100

        result = collect_precision_code_search_context("project-1", ["get_file_tree"])

    mock_scan.assert_called_once_with("project-1", "file")
    assert result.metadata["refreshed_index"]
    assert result.metadata["stale_hit"]
    assert result.metadata["refresh_reasons"] == ["stale_file_index", "stale_symbol_index"]
    assert result.metadata["file_index_age_minutes"] is not None
    assert result.metadata["symbol_index_age_minutes"] is not None


def test_collect_precision_code_search_context_skips_refresh_for_workflow_meta_queries() -> None:
    with patch(
        "app.services.context_gatherer.precision_code_search.explorer_service.scan"
    ) as mock_scan:
        result = collect_precision_code_search_context(
            "project-1",
            ["Confirm workflow cleanup status and closeout coordination."],
        )

    mock_scan.assert_not_called()
    assert result.metadata["skipped_reason"] == "workflow_meta_low_signal"


def test_collect_precision_code_search_context_tracks_fresh_index_telemetry() -> None:
    with (
        patch(
            "app.services.context_gatherer.precision_code_search.explorer_service.get_stats",
            return_value={"total": 12, "last_scanned": "3026-03-10T17:00:00+00:00"},
        ),
        patch(
            "app.services.context_gatherer.precision_code_search.get_symbol_stats",
            return_value={"count": 4, "last_updated": "3026-03-10T17:00:00+00:00"},
        ),
        patch(
            "app.services.context_gatherer.precision_code_search.search_symbols",
            return_value=[],
        ),
        patch(
            "app.services.context_gatherer.precision_code_search.get_entries",
            return_value=[],
        ),
    ):
        result = collect_precision_code_search_context("project-1", ["get_file_tree"])

    assert not result.metadata["stale_hit"]
    assert result.metadata["refresh_reasons"] == []
    assert result.metadata["file_total"] == 12
    assert result.metadata["file_last_scanned"] == "3026-03-10T17:00:00+00:00"
    assert result.metadata["symbol_last_updated"] == "3026-03-10T17:00:00+00:00"
