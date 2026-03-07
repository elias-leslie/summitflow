"""Tests for explorer-backed context gathering."""

from __future__ import annotations

from unittest.mock import patch

from app.services.context_gatherer.explorer_collector import gather_explorer_context


def test_gather_explorer_context_includes_symbol_matches() -> None:
    """Relevant symbol matches should be included ahead of broader file listings."""
    with (
        patch("app.services.context_gatherer.explorer_collector.search_symbols") as mock_search,
        patch(
            "app.services.context_gatherer.explorer_collector.list_related_entries_for_file"
        ) as mock_related,
        patch("app.services.context_gatherer.explorer_collector.get_entries") as mock_entries,
    ):
        mock_search.return_value = [
            {
                "symbol_id": "backend/app/api/files.py::get_file_tree#function",
                "name": "get_file_tree",
                "kind": "function",
                "file_path": "backend/app/api/files.py",
                "signature": "def get_file_tree(path: str) -> dict[str, str]",
                "summary": "List directory entries for file tree navigation.",
            }
        ]
        mock_related.return_value = [
            {
                "entry_type": "endpoint",
                "path": "GET /files/tree",
                "metadata": {
                    "source_file": "backend/app/api/files.py",
                    "depends_on_tables": ["files"],
                },
            }
        ]
        mock_entries.side_effect = [
            [{"path": "backend/app/api/files.py", "name": "files.py"}],
            [{"path": "GET /files/tree", "metadata": {"method": "GET"}}],
            [{"name": "files"}],
        ]

        context = gather_explorer_context("project-1", "get_file_tree")

    assert mock_entries.call_count == 3
    assert "## Relevant Symbols" in context
    assert "`get_file_tree`" in context
    assert "GET /files/tree" in context
    assert "tables: files" in context
